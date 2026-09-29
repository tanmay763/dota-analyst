"""The grid skill's merge script keeps a user's own layouts (ADR 0006)."""

import importlib.util
import json
from pathlib import Path

SCRIPT = (
    Path(__file__).parents[1] / "plugin/skills/hero-grid-builder/scripts/merge_grid.py"
)
spec = importlib.util.spec_from_file_location("merge_grid", SCRIPT)
merge_grid = importlib.util.module_from_spec(spec)
spec.loader.exec_module(merge_grid)


def config(name, heroes):
    return {
        "config_name": name,
        "categories": [{"category_name": "x", "hero_ids": heroes}],
    }


def test_same_names_are_replaced_in_place_and_new_ones_appended():
    current = {
        "version": 3,
        "configs": [config("Mine", [1]), config("Tiers", [2]), config("Old", [3])],
    }
    new = {"version": 3, "configs": [config("Tiers", [9]), config("Counters", [8])]}
    merged = merge_grid.merge(current, new)
    assert [c["config_name"] for c in merged["configs"]] == [
        "Mine",
        "Tiers",
        "Old",
        "Counters",
    ]
    assert merged["configs"][1]["categories"][0]["hero_ids"] == [9]


def test_the_cli_writes_the_merged_file(tmp_path):
    (tmp_path / "current.json").write_text(
        json.dumps({"version": 3, "configs": [config("Mine", [1])]})
    )
    (tmp_path / "new.json").write_text(
        json.dumps({"version": 3, "configs": [config("Tiers", [2])]})
    )
    out = tmp_path / "merged.json"
    code = merge_grid.main(
        [
            "merge_grid.py",
            str(tmp_path / "current.json"),
            str(tmp_path / "new.json"),
            str(out),
        ]
    )
    assert code == 0
    assert [c["config_name"] for c in json.loads(out.read_text())["configs"]] == [
        "Mine",
        "Tiers",
    ]
