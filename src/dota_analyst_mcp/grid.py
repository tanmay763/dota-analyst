"""Hero grids from layouts of hero names, and the stateless download link (ADR 0006).

Claude describes each layout as rows of categories of hero *names*; `Heroes` resolves them
(forgiving of case and punctuation, as in ../dota/src/dota/web/tools.py) and `layout` places
them. The download link carries the whole grid in its path, compressed, so `/grid/<blob>.json`
needs no storage and no sign-in.
"""

import base64
import difflib
import json
import re
import zlib

from dota_analyst_mcp import layout

HEROES_QUERY = "{ constants { heroes { id displayName shortName } } }"
MAX_BLOB_CHARS = 6000  # keeps download URLs well under common URL limits
MAX_SPEC_BYTES = 64 * 1024  # a decompressed blob larger than this is refused


class GridError(ValueError):
    """A problem with a requested grid that Claude should read and fix."""


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


class Heroes:
    """Hero names <-> IDs from Stratz's `constants.heroes`."""

    def __init__(self, rows: list[dict]):
        self.names = {int(r["id"]): str(r["displayName"]) for r in rows}
        self.short_names = {int(r["id"]): str(r["shortName"]) for r in rows}
        self._ids: dict[str, int] = {}
        for hero_id, name in self.names.items():
            self._ids[_norm(name)] = hero_id
            self._ids.setdefault(_norm(self.short_names[hero_id]), hero_id)

    @classmethod
    def from_constants(cls, data: dict) -> "Heroes":
        return cls(
            [h for h in data["constants"]["heroes"] if h and h.get("displayName")]
        )

    def resolve(self, name: str) -> int:
        hero_id = self._ids.get(_norm(str(name)))
        if hero_id is None:
            close = difflib.get_close_matches(
                str(name), list(self.names.values()), n=3, cutoff=0.5
            )
            hint = f" Did you mean: {', '.join(close)}?" if close else ""
            raise GridError(f"No hero named {name!r}.{hint}")
        return hero_id

    def card(self, hero_id: int) -> dict:
        return {
            "name": self.names.get(hero_id, f"Hero {hero_id}"),
            "short_name": self.short_names.get(hero_id, ""),
        }


def resolve_layouts(layouts: list[dict], heroes: Heroes) -> list[dict]:
    """Layouts of hero names -> layouts of hero IDs, reporting every unknown name at once."""
    if not isinstance(layouts, list) or not layouts:
        raise GridError("Give at least one layout: [{name, rows: [[{name, heroes}]]}].")
    unknown, resolved = [], []
    for spec in layouts:
        if not isinstance(spec, dict) or not isinstance(spec.get("rows"), list):
            raise GridError("Each layout needs a name and rows of categories.")
        rows = []
        for row in spec["rows"]:
            if not isinstance(row, list):
                raise GridError("Each row must be a list of categories.")
            categories = []
            for category in row:
                if not isinstance(category, dict):
                    raise GridError("Each category needs a name and a list of heroes.")
                ids = []
                for hero in category.get("heroes") or []:
                    try:
                        ids.append(heroes.resolve(hero))
                    except GridError as exc:
                        unknown.append(str(exc))
                categories.append(
                    {"name": str(category.get("name", "")), "hero_ids": ids}
                )
            rows.append(categories)
        resolved.append({"name": spec.get("name"), "rows": rows})
    if unknown:
        raise GridError("Nothing was built. " + " ".join(unknown))
    return resolved


MAX_BORDERLINE = 5  # a swipe stack longer than this stops being a quick check


def resolve_candidates(candidates: list[dict], heroes: Heroes) -> list[dict]:
    """Borderline heroes by name -> swipe cards (ADR 0011), reporting every unknown name."""
    if not isinstance(candidates, list) or not candidates:
        raise GridError("Give at least one borderline hero: [{hero, category, note}].")
    if len(candidates) > MAX_BORDERLINE:
        raise GridError(
            f"Give at most {MAX_BORDERLINE} borderline heroes; settle the rest yourself."
        )
    unknown, cards = [], []
    for candidate in candidates:
        try:
            hero_id = heroes.resolve(candidate.get("hero", ""))
        except GridError as exc:
            unknown.append(str(exc))
            continue
        cards.append(
            {
                "hero_id": hero_id,
                **heroes.card(hero_id),
                "category": str(candidate.get("category", "")),
                "note": str(candidate.get("note", "")),
            }
        )
    if unknown:
        raise GridError("Nothing was shown. " + " ".join(unknown))
    if len({c["hero_id"] for c in cards}) < len(cards):
        raise GridError("Each borderline hero can appear only once.")
    return cards


def encode(layouts: list[dict]) -> str:
    """Layouts of hero IDs -> the URL-safe blob of a download link."""
    text = json.dumps(layouts, separators=(",", ":"), ensure_ascii=False)
    blob = (
        base64.urlsafe_b64encode(zlib.compress(text.encode(), 9)).decode().rstrip("=")
    )
    if len(blob) > MAX_BLOB_CHARS:
        raise GridError(
            "The grid is too large for a download link; split it into fewer layouts."
        )
    return blob


def decode(blob: str) -> list[dict]:
    """The inverse of `encode`, refusing anything malformed or oversized."""
    if len(blob) > MAX_BLOB_CHARS or not re.fullmatch(r"[A-Za-z0-9_-]+", blob):
        raise GridError("Not a hero grid link.")
    try:
        raw = base64.urlsafe_b64decode(blob + "=" * (-len(blob) % 4))
        inflater = zlib.decompressobj()
        text = inflater.decompress(raw, MAX_SPEC_BYTES)
        if inflater.unconsumed_tail:
            raise GridError("Not a hero grid link.")
        layouts = json.loads(text)
    except (ValueError, zlib.error) as exc:
        raise GridError("Not a hero grid link.") from exc
    if not isinstance(layouts, list):
        raise GridError("Not a hero grid link.")
    return layouts


def to_json(grid: dict) -> str:
    """hero_grid_config.json, indented like the weekly grids."""
    return json.dumps(grid, indent=4)


def place(layouts: list[dict]) -> tuple[dict, list[str]]:
    """Layouts of hero IDs -> (Valve hero grid, warnings); bad shapes become GridErrors."""
    try:
        return layout.place_grid(layouts)
    except (ValueError, TypeError, AttributeError) as exc:
        raise GridError(str(exc)) from exc
