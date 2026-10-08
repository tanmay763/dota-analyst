"""Hero grids from layouts of hero names, and the stateless download link (ADR 0006)."""

import base64
import json
import random
import zlib

import pytest

from dota_analyst_mcp import grid, layout
from dota_analyst_mcp.grid import GridError, Heroes

HEROES = Heroes(
    [
        {"id": 1, "displayName": "Anti-Mage", "shortName": "antimage"},
        {"id": 2, "displayName": "Axe", "shortName": "axe"},
        {"id": 14, "displayName": "Pudge", "shortName": "pudge"},
        {"id": 86, "displayName": "Rubick", "shortName": "rubick"},
    ]
)


def test_hero_names_resolve_forgivingly():
    assert HEROES.resolve("anti mage") == 1
    assert HEROES.resolve("ANTIMAGE") == 1  # the short name
    assert HEROES.resolve("Pudge") == 14


def test_an_unknown_hero_suggests_close_names():
    with pytest.raises(GridError, match="Rubick"):
        HEROES.resolve("Rubik")


def test_every_unknown_name_is_reported_at_once():
    layouts = [
        {"name": "A", "rows": [[{"name": "x", "heroes": ["Pudge", "Pudgee"]}]]},
        {"name": "B", "rows": [[{"name": "y", "heroes": ["Axxe"]}]]},
    ]
    with pytest.raises(GridError) as info:
        grid.resolve_layouts(layouts, HEROES)
    assert "Pudgee" in str(info.value) and "Axxe" in str(info.value)
    assert str(info.value).startswith("Nothing was built.")


def test_layouts_resolve_to_hero_ids_in_order():
    layouts = [
        {"name": "Tiers", "rows": [[{"name": "S", "heroes": ["Rubick", "Axe"]}]]}
    ]
    assert grid.resolve_layouts(layouts, HEROES) == [
        {"name": "Tiers", "rows": [[{"name": "S", "hero_ids": [86, 2]}]]}
    ]


def test_a_link_round_trips_the_grid():
    layouts = [
        {
            "name": "Tiers",
            "rows": [
                [{"name": "S", "hero_ids": [86, 2]}, {"name": "A", "hero_ids": [1]}]
            ],
        }
    ]
    blob = grid.encode(layouts)
    assert grid.decode(blob) == layouts
    assert grid.place(grid.decode(blob)) == layout.place_grid(layouts)


@pytest.mark.parametrize(
    "blob", ["", "not a blob!", "a" * (grid.MAX_BLOB_CHARS + 1), "AAAA"]
)
def test_malformed_links_are_refused(blob):
    with pytest.raises(GridError):
        grid.decode(blob)


def test_a_decompression_bomb_is_refused():
    bomb = (
        base64.urlsafe_b64encode(zlib.compress(b"[" + b" " * 1_000_000 + b"]", 9))
        .decode()
        .rstrip("=")
    )
    assert len(bomb) <= grid.MAX_BLOB_CHARS
    with pytest.raises(GridError):
        grid.decode(bomb)


def test_an_oversized_grid_asks_for_fewer_layouts():
    shuffle = random.Random(0)
    layouts = [
        {
            "name": f"L{i}",
            "rows": [
                [
                    {"name": f"c{j}", "hero_ids": shuffle.sample(range(1, 130), 129)}
                    for j in range(3)
                ]
            ],
        }
        for i in range(40)
    ]
    with pytest.raises(GridError, match="fewer layouts"):
        grid.encode(layouts)


def test_bad_layout_shapes_become_grid_errors():
    with pytest.raises(GridError):
        grid.place([{"name": "", "rows": []}])


# --- the download route -----------------------------------------------------------------


def test_the_download_route_serves_hero_grid_config(http):
    layouts = [{"name": "Tiers", "rows": [[{"name": "S", "hero_ids": [86, 2]}]]}]
    response = http.get(f"/grid/{grid.encode(layouts)}.json")
    assert response.status_code == 200
    assert (
        response.headers["content-disposition"]
        == 'attachment; filename="hero_grid_config.json"'
    )
    assert json.loads(response.text) == layout.place_grid(layouts)[0]


def test_the_download_route_refuses_junk(http):
    assert http.get("/grid/nonsense.json").status_code == 400


def test_borderline_heroes_become_cards_with_portrait_names():
    cards = grid.resolve_candidates(
        [{"hero": "pudge", "category": "Offlane · B", "note": "49% win rate"}], HEROES
    )
    assert cards == [
        {
            "hero_id": 14,
            "name": "Pudge",
            "short_name": "pudge",
            "category": "Offlane · B",
            "note": "49% win rate",
        }
    ]


def test_unknown_borderline_heroes_are_all_reported():
    with pytest.raises(GridError, match="Pudgee.*Rubik"):
        grid.resolve_candidates([{"hero": "Pudgee"}, {"hero": "Rubik"}], HEROES)


@pytest.mark.parametrize(
    "candidates, message",
    [
        ([], "at least one"),
        ([{"hero": "Axe"}] * 6, "at most 5"),
        ([{"hero": "Axe"}, {"hero": "axe"}], "only once"),
    ],
)
def test_a_swipe_stack_is_short_and_has_no_repeats(candidates, message):
    with pytest.raises(GridError, match=message):
        grid.resolve_candidates(candidates, HEROES)
