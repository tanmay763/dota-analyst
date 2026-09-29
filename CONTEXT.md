# dota-analyst

Open-ended analysis of Dota 2 statistics from Stratz, which a user can turn into an in-game hero grid when the analysis is done.

## Language

### People

**User**:
A person using the plugin to analyse Dota statistics or build a hero grid.

**Player**:
The person behind a Steam account whose matches are analysed. A player may or may not be a user.

**Maintainer**:
The person who teaches the cookbook, deploys the server and owns this repository.

### Hero grids

**Hero grid**:
The file a player loads into the Dota client's hero picker. It holds one or more layouts.
_Avoid_: grid config, config file

**Layout**:
One named, selectable arrangement of heroes inside a hero grid, designed with a user in conversation.
_Avoid_: config, custom layout

**Row**:
A horizontal band of categories across a layout.

**Category**:
A labelled box of heroes inside a row.
_Avoid_: group, bucket

**Tier list**:
A layout whose categories are tiers, best first.

**Tier**:
A labelled rank group in a tier list, such as S to F. Each tier list's ranking logic is set per request, either by the user or chosen and stated by the analyst; there is no standing tier model.

### Matches and heroes

**Match**:
One game of Dota 2, with ten picks.

**Pick**:
One hero played by one player in one match. Stratz's `matchCount` on hero statistics counts picks, not matches.
_Avoid_: hero-slot

**Position**:
The slot a hero is played in: 1 Carry, 2 Mid, 3 Offlane, 4 Soft support, 5 Hard support.
_Avoid_: role

**Lane**:
Where a hero spends the laning phase: safe lane, mid lane, off lane, jungle or roaming. Distinct from position: a position 4 can lane in the safe lane.

**Hero pool**:
The heroes a player plays often enough to count as their own. The threshold is set per request, by the user or stated by the analyst; there is no standing one.
_Avoid_: comfort picks

### Statistics

**Win rate**:
The share of a hero's picks that won.

**Pick rate**:
The share of matches in which a hero was picked.
_Avoid_: meta (say which rates were used)

### Ranks

**Rank**:
One medal, Herald through Immortal. "X+" means rank X and every rank above it.
_Avoid_: medal, MMR bracket

**Basic bracket**:
One of four fixed pairs of adjacent ranks: Herald–Guardian, Crusader–Archon, Legend–Ancient, Divine–Immortal.
_Avoid_: bracket (on its own)

### Time

**Period**:
The span of time a statistic covers, built from Stratz buckets: hours, days, weeks, months or patches. Every number is stated with its period. Unless the user says otherwise, it is the latest complete week. The most recent bucket may still be in progress.

**Patch**:
A game version, such as 7.38b.
_Avoid_: game version, update
