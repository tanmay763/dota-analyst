"""Merge a new Dota hero grid into the user's current one.

    python3 merge_grid.py current.json new.json merged.json

Layouts ("configs") in the new grid replace current layouts with the same name; every
other current layout is kept, in order, and new ones are appended. Standard library only,
so it runs in any code-execution sandbox.
"""

import json
import sys


def merge(current: dict, new: dict) -> dict:
    replacements = {c["config_name"]: c for c in new.get("configs", [])}
    merged = []
    for config in current.get("configs", []):
        name = config.get("config_name")
        merged.append(replacements.pop(name) if name in replacements else config)
    merged.extend(c for c in new.get("configs", []) if c["config_name"] in replacements)
    return {
        **current,
        "version": new.get("version", current.get("version", 3)),
        "configs": merged,
    }


def main(argv: list[str]) -> int:
    if len(argv) != 4:
        print(__doc__.strip())
        return 2
    with open(argv[1], encoding="utf-8") as f:
        current = json.load(f)
    with open(argv[2], encoding="utf-8") as f:
        new = json.load(f)
    merged = merge(current, new)
    with open(argv[3], "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=4)
    kept = len(merged["configs"]) - len(new.get("configs", []))
    print(
        f"{len(merged['configs'])} layouts: {len(new.get('configs', []))} from the new grid, {kept} kept"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
