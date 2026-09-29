"""Layouts: rows of named categories placed on the hero grid as the game draws them.

Copied unchanged in behaviour from ../dota/src/dota/core/custom_layout.py (ADR 0008). A
layout (CONTEXT.md) is designed with a user in conversation. Claude describes it as rows of
categories with hero IDs and never does geometry; this module places it:

    {"name": "My carries", "rows": [[{"name": "Farm", "hero_ids": [1, 94]}, ...], ...]}

becomes one Valve hero grid config. Placement mirrors the weekly grid (equal columns
across the 1200-wide canvas, 25 units between rows) with one difference: the game clips
cards that overflow a category, so each category is made tall enough to show them all.

Card geometry was calibrated against in-game screenshots (../dota issue #13).
"""

import math

CANVAS_WIDTH = 1200
SCREEN_HEIGHT = 600  # one screen of the in-game grid; taller layouts scroll
ROW_GAP = 25  # between rows of categories; the weekly grid's 100 pitch minus its 75

# In-game card geometry, in grid units (2.30 px each at 3840x2160).
TITLE_HEIGHT = 14.1  # from a category's y to its first row of cards (label sits above)
AREA_MARGIN = 12.5  # category width minus the width its cards are fitted into
CARD_MAX = 35.2  # widest card
CARD_MIN = 21.3  # narrowest card; below this width cards wrap instead of shrinking
CARD_ASPECT = 140 / 81  # card height / width
GAP_RATIO = 0.19  # gap between cards, as a fraction of card width

# Below this many full-size cards per row, a category's cards get too small to read.
MIN_FULL_CARDS_PER_ROW = 3


def card_width(area_width: float, heroes: int) -> float:
    """The game's card width: all heroes in one row, clamped to the card size range."""
    fit = area_width / (heroes * (1 + GAP_RATIO) - GAP_RATIO)
    return max(CARD_MIN, min(CARD_MAX, fit))


def cards_per_row(area_width: float, width: float) -> int:
    # The epsilon keeps cards sized to fit exactly from computing as 4.999 per row.
    return max(
        1,
        math.floor((area_width + GAP_RATIO * width) / (width * (1 + GAP_RATIO)) + 1e-9),
    )


def category_height(width: float, heroes: int) -> float:
    """Tall enough to show every card; the game would clip the rest."""
    if heroes == 0:
        return TITLE_HEIGHT + CARD_MAX * CARD_ASPECT
    area = width - AREA_MARGIN
    card = card_width(area, heroes)
    rows = math.ceil(heroes / cards_per_row(area, card))
    return TITLE_HEIGHT + rows * card * CARD_ASPECT + (rows - 1) * card * GAP_RATIO


def place_layout(layout: dict) -> tuple[dict, list[str]]:
    """One layout -> (Valve config, warnings for Claude to act on)."""
    name, rows = _validated(layout)
    warnings: list[str] = []
    categories = []
    y = 0.0
    for row in rows:
        width = CANVAS_WIDTH / len(row)
        area = width - AREA_MARGIN
        if cards_per_row(area, CARD_MAX) < MIN_FULL_CARDS_PER_ROW:
            warnings.append(
                f"{name}: {len(row)} categories in one row makes them too narrow "
                "for readable cards; split the row."
            )
        placed = []
        for column, category in enumerate(row):
            hero_ids = _unique(category, warnings)
            placed.append(
                {
                    "category_name": category["name"],
                    "x_position": _num(column * width),
                    "y_position": _num(y),
                    "width": _num(width),
                    "height": _num(category_height(width, len(hero_ids))),
                    "hero_ids": hero_ids,
                }
            )
        categories.extend(placed)
        y += max(c["height"] for c in placed) + ROW_GAP
    bottom = y - ROW_GAP
    if bottom > SCREEN_HEIGHT:
        warnings.append(
            f"{name}: {bottom:.0f} units tall, more than one screen ({SCREEN_HEIGHT}); "
            "players will have to scroll."
        )
    return {"config_name": name, "categories": categories}, warnings


def place_grid(layouts: list[dict]) -> tuple[dict, list[str]]:
    """Layouts -> a Valve hero grid (hero_grid_config.json) plus warnings."""
    names = [layout.get("name") for layout in layouts]
    duplicates = sorted({n for n in names if names.count(n) > 1})
    if duplicates:
        raise ValueError(f"layout names must be unique: {', '.join(duplicates)}")
    configs, warnings = [], []
    for layout in layouts:
        config, layout_warnings = place_layout(layout)
        configs.append(config)
        warnings.extend(layout_warnings)
    return {"version": 3, "configs": configs}, warnings


def _validated(layout: dict) -> tuple[str, list[list[dict]]]:
    name = layout.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("a layout needs a non-empty name")
    rows = layout.get("rows")
    if not rows or not all(isinstance(row, list) and row for row in rows):
        raise ValueError(f"{name}: a layout needs at least one row, and no empty rows")
    for row in rows:
        for category in row:
            if not isinstance(category.get("name"), str):
                # ValueError, not TypeError: the tool hands it to the model as bad input.
                raise ValueError(f"{name}: every category needs a name")  # noqa: TRY004
            ids = category.get("hero_ids")
            if not isinstance(ids, list) or not all(
                isinstance(i, int) and not isinstance(i, bool) and i > 0 for i in ids
            ):
                raise ValueError(
                    f"{name}: category {category['name']!r} needs a list of hero IDs"
                )
    return name, rows


def _unique(category: dict, warnings: list[str]) -> list[int]:
    ids = list(dict.fromkeys(category["hero_ids"]))
    if len(ids) < len(category["hero_ids"]):
        warnings.append(f"{category['name']}: dropped duplicate heroes")
    return ids


def _num(value: float) -> float | int:
    """Whole numbers as ints (like the weekly grid), others to 2 decimals."""
    rounded = round(value, 2)
    return int(rounded) if rounded == int(rounded) else rounded
