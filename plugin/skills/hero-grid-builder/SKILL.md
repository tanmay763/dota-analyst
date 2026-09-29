---
name: hero-grid-builder
description: >-
  Build a Dota 2 in-game hero grid (hero_grid_config.json) from an analysis or a list
  of heroes. Use only when the user asks for a hero grid, a layout, or a tier list to
  load into the Dota client, or says yes to an offer to make one.
---

# Building a hero grid

A **hero grid** is the file the Dota client's hero picker loads. It holds one or more
**layouts**. Each layout is **rows** of labelled **categories**, and each category is
a box of heroes, best first. The connector's `build_hero_grid` tool places and sizes
everything, returns warnings, shows a preview where the app supports it, and gives a
download link.

## 1. Agree on the grid before building

Only build once the user wants a grid and the analysis behind it is done. Settle:

- **Which layouts**, with a unique name for each. The name is what the user picks in
  the client, so make it say what it is, e.g. "Pos 1 tiers · Divine+ · 7.39 wk 38".
- **What goes in each category**, and in what order.
- For a **tier list**, the ranking logic. Use the user's if they gave one. Otherwise
  propose one in a sentence (metric, period, ranks, positions, minimum sample, tier
  cut-offs) and get a yes before building.
- For a **hero pool** layout, the threshold that makes a hero part of the pool (e.g.
  ≥ 10 ranked matches in the last 8 weeks). Get it from the user or state yours.

Every hero in the grid should come from the analysis in this conversation or from the
user; don't pad categories with heroes you haven't justified.

## 2. Build

Call `build_hero_grid` with every layout, using hero names as Stratz shows them
("Anti-Mage", "Nature's Prophet"). Aim for:

- **At most 3 categories per row.** More makes the cards too small to read.
- **One screen per layout.** The tool warns when a layout would need scrolling.
- **Heroes best first** within each category.

If the tool reports unknown heroes, fix the names and call again (nothing is built
until every name resolves). Act on warnings: split crowded rows or trim categories,
then rebuild.

## 3. Hand it over

The reply from the tool includes a download link. Tell the user:

1. **Download** `hero_grid_config.json` from the link (the preview's Download button
   opens the same link).
2. **Install**: in Steam, find the Dota folder
   `Steam/userdata/<Steam ID>/570/remote/cfg/` and put the file there, then restart
   Dota. The hero grid is in the hero picker's grid view.
3. **Warning:** this **replaces** the hero grid already in that folder. To keep their
   existing layouts, they can upload their current `hero_grid_config.json` here and
   you'll merge the two (below).

## Changing a grid

When the user wants changes ("move Pudge to the offlane box", "add a row of
supports"), call `build_hero_grid` again with **the whole grid**, including the
layouts that didn't change. The preview and the link update together.

## Merging with the user's current grid

If the user uploads their current `hero_grid_config.json` and code execution is
available, download the new grid from the link and run:

```sh
python3 ${CLAUDE_SKILL_DIR}/scripts/merge_grid.py current.json new.json merged.json
```

(In chat, the skill's folder is copied into the sandbox, so the script is at
`scripts/merge_grid.py` next to this file.)

Layouts in the new grid replace current ones **with the same name**; all other current
layouts are kept, and new ones are added after them. Give the user `merged.json` to
install instead. Without code execution, tell them the merge isn't possible here and
let them choose between replacing their grid or keeping it.
