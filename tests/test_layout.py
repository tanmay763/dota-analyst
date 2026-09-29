"""Layouts: rows of named categories placed on the hero grid the way the game draws them.

Ported from ../dota/tests/test_custom_layout.py. Expected values come from the in-game
calibration posted on ../dota issue #13 (4K screenshots of the golden LEGEND_ANCIENT and LAID
Counterpicker layouts), not from the code under test.
"""

import pytest

from dota_analyst_mcp import layout as cl

WEEKLY_AREA = 187.5  # card area of a 200-wide category, as measured in game


# --- the game's card fitting rule ------------------------------------------------------


@pytest.mark.parametrize(
    "heroes,width",
    [
        (1, 35.2),  # largest card
        (2, 35.2),
        (5, 32.55),  # shrunk to fit one row (74 px at 4K)
        (7, 23.03),  # shrunk to fit one row (53 px at 4K)
        (9, 21.3),  # smallest card (49 px at 4K); from here cards wrap
        (15, 21.3),
    ],
)
def test_card_width_matches_the_game(heroes, width):
    assert cl.card_width(WEEKLY_AREA, heroes) == pytest.approx(width, abs=0.01)


@pytest.mark.parametrize(
    "heroes,per_row",
    [
        (2, 4),  # row capacity at full size: the counterpicker layouts' 4 cards
        (5, 5),
        (7, 7),
        (9, 7),  # the smallest card wraps after 7
        (15, 7),
    ],
)
def test_cards_per_row_matches_the_game(heroes, per_row):
    """How many cards fit one row at the size the game picks for `heroes`."""
    width = cl.card_width(WEEKLY_AREA, heroes)
    assert cl.cards_per_row(WEEKLY_AREA, width) == per_row


def test_heroes_sized_to_fit_one_row_stay_in_one_row():
    """Regression: in floating point, 15 cards sized to fill a row exactly compute as
    14.999... per row, which would wrap the 15th card and double the category's height."""
    area = 600 - 12.5  # each of two categories in a row
    card = area / (15 * 1.19 - 0.19)  # the game shrinks 15 cards to fill one row
    assert cl.card_width(area, 15) == pytest.approx(card)
    assert cl.cards_per_row(area, card) == 15
    assert cl.category_height(600, 15) == pytest.approx(
        14.1 + card * 140 / 81, abs=0.01
    )


# --- placing a layout ------------------------------------------------------------------


def _category(name, heroes):
    return {"name": name, "hero_ids": list(range(1, heroes + 1))}


def _placed(rows, name="Custom"):
    config, warnings = cl.place_layout({"name": name, "rows": rows})
    return config, warnings


def test_a_row_of_six_matches_the_weekly_grid_geometry():
    config, warnings = _placed([[_category(f"C{i}", 2) for i in range(6)]])
    categories = config["categories"]
    assert [c["x_position"] for c in categories] == [0, 200, 400, 600, 800, 1000]
    assert {c["width"] for c in categories} == {200}
    assert {c["y_position"] for c in categories} == {0}
    # One row of full-size cards: the weekly grid's 75.
    assert all(c["height"] == pytest.approx(75, abs=0.1) for c in categories)
    assert warnings == []


def test_categories_keep_their_names_and_heroes_in_order():
    config, _ = _placed([[{"name": "Carries", "hero_ids": [3, 1, 2]}]], name="Mine")
    assert config["config_name"] == "Mine"
    (category,) = config["categories"]
    assert category["category_name"] == "Carries"
    assert category["hero_ids"] == [3, 1, 2]


def test_a_crowded_category_grows_to_show_every_card():
    """The game clips cards past a category's bottom; placement must not let it."""
    config, _ = _placed([[_category(f"C{i}", 15 if i == 0 else 2) for i in range(6)]])
    crowded = config["categories"][0]
    # 15 heroes at the smallest card wrap into 3 rows of up to 7.
    card = 21.3
    expected = 14.1 + 3 * card * 1.728 + 2 * card * 0.19
    assert crowded["height"] == pytest.approx(expected, abs=0.2)


def test_rows_stack_below_the_tallest_category_with_the_weekly_gap():
    rows = [
        [_category(f"C{i}", 15 if i == 2 else 2) for i in range(6)],
        [_category("Next", 2)],
    ]
    config, _ = _placed(rows)
    *first_row, nxt = config["categories"]
    tallest = first_row[2]
    assert {c["y_position"] for c in first_row} == {0}
    assert tallest["height"] > first_row[0]["height"]
    assert nxt["y_position"] == pytest.approx(tallest["height"] + 25, abs=0.01)


def test_wider_categories_fit_more_cards_per_row():
    config, _ = _placed([[_category("Wide", 12)]])
    (wide,) = config["categories"]
    assert wide["width"] == 1200
    # Twelve full-size cards fit one row of a 1200-wide category.
    assert wide["height"] == pytest.approx(75, abs=0.1)


def test_duplicate_heroes_are_dropped_with_a_warning():
    config, warnings = _placed([[{"name": "Dup", "hero_ids": [5, 7, 5]}]])
    assert config["categories"][0]["hero_ids"] == [5, 7]
    assert any("Dup" in w and "duplicate" in w for w in warnings)


def test_a_layout_taller_than_one_screen_warns_about_scrolling():
    rows = [[_category(f"R{r}C{c}", 15) for c in range(6)] for r in range(4)]
    _, warnings = _placed(rows)
    assert any("scroll" in w for w in warnings)


def test_too_many_categories_in_a_row_warns_about_tiny_cards():
    _, warnings = _placed([[_category(f"C{i}", 2) for i in range(12)]])
    assert any("narrow" in w for w in warnings)


@pytest.mark.parametrize(
    "layout",
    [
        {"name": "", "rows": [[{"name": "A", "hero_ids": [1]}]]},
        {"name": "No rows", "rows": []},
        {"name": "Empty row", "rows": [[]]},
        {"name": "Bad heroes", "rows": [[{"name": "A", "hero_ids": ["axe"]}]]},
    ],
)
def test_malformed_layouts_are_rejected(layout):
    with pytest.raises(ValueError):
        cl.place_layout(layout)


# --- the whole hero grid ---------------------------------------------------------------


def test_place_grid_builds_a_valve_hero_grid_in_order():
    layouts = [
        {"name": "First", "rows": [[_category("A", 2)]]},
        {"name": "Second", "rows": [[_category("B", 3), _category("C", 1)]]},
    ]
    grid, warnings = cl.place_grid(layouts)
    assert grid["version"] == 3
    assert [c["config_name"] for c in grid["configs"]] == ["First", "Second"]
    assert warnings == []


def test_layout_names_must_be_unique():
    layout = {"name": "Same", "rows": [[_category("A", 1)]]}
    with pytest.raises(ValueError, match="Same"):
        cl.place_grid([layout, layout])


def test_placed_grid_serializes_like_the_weekly_grid():
    import json

    from dota_analyst_mcp import grid as hero_grid

    grid, _ = cl.place_grid([{"name": "Only", "rows": [[_category("A", 2)]]}])
    parsed = json.loads(hero_grid.to_json(grid))
    (category,) = parsed["configs"][0]["categories"]
    assert set(category) == {
        "category_name",
        "x_position",
        "y_position",
        "width",
        "height",
        "hero_ids",
    }
