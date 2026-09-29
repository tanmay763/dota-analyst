---
name: stratz-analysis
description: >-
  Analyse Dota 2 statistics from Stratz. Use when the user asks about Dota 2 data of
  any kind: hero win or pick rates, the meta, tier lists, matchups, items, lanes,
  positions, ranks, patches, a player's matches or hero pool, pro leagues and teams.
---

# Dota 2 analysis with Stratz

You answer Dota 2 questions from live Stratz data through the dota-analyst connector's
tools. The core discipline: **bulk data never enters the conversation**. Stratz
responses stay on the server; you see their shape and the rows your SQL returns.

If the connector's tools aren't available, ask the user to connect **Dota Analyst**
from the plugin's Connectors tab (they'll need a free Stratz API token from
stratz.com/api) and stop there. Never invent numbers.

## The loop

1. **Pin the question down.** Work out the heroes, positions (1 Carry … 5 Hard support),
   ranks ("Divine+" means Divine and Immortal), game mode and **period**. Default to the
   latest *complete* week and say so. Stratz also buckets hero statistics by hour, day,
   month and patch (`winHour`, `winDay`, `winMonth`, `winGameVersion`); use those when
   the user asks for them. Ask one short question only if the answer would change the
   query.
2. **Check the cookbook first.** Call `stratz_cookbook` with no section to list what's
   known, then read every section that fits. Its query shapes work, so use them as
   they are. Its traps are real: for example, hero `matchCount` counts picks (ten per
   match), and the most recent bucket may still be in progress.
3. **Look the schema up only when the cookbook doesn't cover it.** Use
   `stratz_schema_search` with a word from the question ("lane", "item", "league"),
   then `stratz_schema_type` on the types it finds. Start from `DotaQuery`, the root.
   Never try to read the whole schema.
4. **Fetch once.** `stratz_fetch` runs one read-only GraphQL query and returns a
   dataset handle plus each table's name, row count, columns and five sample rows.
   Pass changing values (ranks, weeks, hero IDs) as GraphQL variables so repeat
   questions hit the cache. Put related data in one query with aliases (hero names
   from `constants { heroes { id displayName } }` alongside the statistics) rather than
   fetching piecemeal.
5. **Peek, then aggregate.** Read the summary to learn the shape, then answer with
   `stratz_aggregate`: DuckDB SQL over one or more datasets, `{"alias": dataset}`, whose
   tables are named `<alias>_<table>`. It returns at most 100 rows, so aggregate, filter
   and order in SQL. Apply rank, position and mode filters to both sides of every rate.
6. **Iterate** when a result looks wrong (a win rate far from 50% on a big sample,
   empty tables, a wrong period): check the cookbook, fix the query and fetch again.
   A GraphQL error comes back verbatim, so fix the field it names; don't retry blindly.
7. **Answer.** Lead with the finding, then a compact markdown table. Always state:
   - the **period** (dates, week, patch), the **ranks**, **positions** and **mode**;
   - the **metric** behind any ranking, with sample sizes where they matter;
   - for "meta", "tier" or "hero pool" requests, the logic you used, such as "tiers by
     win rate, positions 1, Divine+, min 500 picks". These words have no fixed
     definition, so the user's logic wins whenever they give one.

## Win rate and pick rate

- **Win rate** = wins ÷ picks for the hero, within the same filters.
- **Pick rate** = the hero's picks ÷ matches (matches = total picks ÷ 10). Pick rates
  across all heroes sum to about 1000%.
- Match-weighted win rate across all heroes is 50% within a rank and period, which is a
  good sanity check.
- Suppress tiny samples (e.g. under 200 picks) and say that you did.

## Ending an analysis

Finish with the answer. If a hero grid would help (a tier list, a counterpick layout,
the user's hero pool by position), **offer** it in one line, e.g. "Want this as an
in-game hero grid?", and wait. Never build a grid the user hasn't asked for; the
hero-grid-builder skill takes over once they say yes.
