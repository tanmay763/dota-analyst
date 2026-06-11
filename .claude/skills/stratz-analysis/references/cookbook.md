# Stratz cookbook

Mechanical, question-agnostic knowledge about the Stratz API: field semantics,
traps, working query shapes. Read on demand; check here before exploring the
schema for a topic. Append new durable discoveries as new entries (the "Learn"
step of the skill loop). Policy — metric definitions, standing filters,
suggested analyses — does **not** belong here.

## heroStats.winWeek

- `take` = number of most-recent weeks **per hero**, not total rows: the
  result has ~127 heroes × `take` rows.
- `week` is the epoch second of the week's start.
- The most recent week may be in progress — treat a week starting at `T` as
  complete only when `now >= T + 7 days`.
- Sanity: match-weighted mean win rate across heroes is exactly 0.5 per
  bracket/week (every match contributes 5 winning and 5 losing hero slots), so
  `matchCount` counts hero-slots, not matches: divide a bracket/week's
  `SUM(matchCount)` by 10 for the true match count.
- Working shape (bracket as a variable keeps the query text cache-canonical):

  ```graphql
  query ($bracket: [RankBracket], $weeks: Int) {
    heroStats {
      winWeek(take: $weeks, bracketIds: $bracket, gameModeIds: [ALL_PICK_RANKED]) {
        week heroId matchCount winCount
      }
    }
  }
  ```

## constants.heroes

- `query { constants { heroes { id displayName } } }` → ~127-row id→name map
  for readable output; effectively static, fetch with a long `--ttl-days`.
