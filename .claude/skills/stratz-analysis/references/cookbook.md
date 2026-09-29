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

## heroStats.itemFullPurchase (items a hero buys)

- One call per hero: `heroId` is required. Omitting `week` gives the **current,
  in-progress** week; the rows' `week` is a week *number* (e.g. 2960), not epoch
  seconds.
- Rows are per item × `instance` (0 = first copy, 1 = second) × `time` (the
  purchase minute, 0–75), so an item spans many rows: aggregate with
  `SUM(matchCount)` by `itemId` for "most bought", and
  `SUM(time * matchCount) / SUM(matchCount)` for the average purchase minute.
- Item names come from `constants.items { id displayName }` in the same query.
- Working shape (the SQL is for the MCP server's `stratz_aggregate` with
  `datasets: {"p": <dataset>}`, which prefixes every table with `p_`):

  ```graphql
  query ($hero: Short!, $brackets: [RankBracketBasicEnum]) {
    heroStats {
      itemFullPurchase(heroId: $hero, bracketBasicIds: $brackets) {
        week itemId instance time matchCount winCount
      }
    }
    constants { items { id displayName } }
  }
  ```

  ```sql
  SELECT i.displayName AS item, SUM(p.matchCount) AS bought,
         SUM(p.winCount) / SUM(p.matchCount) AS win_rate,
         SUM(p.time * p.matchCount) / SUM(p.matchCount) AS avg_minute
  FROM p_heroStats_itemFullPurchase p JOIN p_constants_items i ON i.id = p.itemId
  GROUP BY 1 ORDER BY bought DESC LIMIT 15
  ```

## match / matches (per-match data)

- **`matches(ids: [Long]!)` is admin-gated** — any selection (even just `id`)
  returns `{"message": "User is not an admin."}`. It also caps at 10 ids
  (`"Requesting Too Many MatchIds. Max Request Size 10."`). For a normal token,
  **loop the singular `match(id: Long!)` query** instead — one cache entry per
  match id, so re-runs are free.
- `match.players[]` is the clean source for picks/wins: `heroId`, `isRadiant`,
  `isVictory` (per player slot — true for all 5 winners), `position`
  (`POSITION_1`..`POSITION_5`). 10 rows per match.
- `match.pickBans[]` is the captains-mode draft. Each row has `isPick`,
  `order`, `isRadiant`. **Bans are the `isPick = false` rows; the banned hero is
  in `bannedHeroId`** (not `heroId` — on ban rows `heroId` mirrors
  `bannedHeroId`). Picks (`isPick = true`) duplicate the `players` roster.
- Tournament/league aggregate: filtering `match.players` by `heroId` gives
  pick count; `sum(isVictory)` gives wins; `pickBans` gives bans. Denominator
  for pick/ban/contest rates = number of matches (one game = 10 picks).
- `league(id: Int!)` returned `null` for a valid leagueId (19101) on this token
  — don't rely on it to label a tournament; the shared `leagueId` across the
  match set is sufficient confirmation.

## constants.heroes

- `query { constants { heroes { id displayName } } }` → ~127-row id→name map
  for readable output; effectively static, fetch with a long `--ttl-days`.

## league / leagues (the league table can omit a live league)

- The league table and the match data are separate: matches can carry a
  `leagueId` that the league endpoints do not know about. Seen on leagueId
  19719 while the event was running — `league(id: 19719)` → null **and**
  `leagues(request: {leagueIds: [19719]})` → `[]`, while individual matches
  returned `leagueId: 19719` fine. An older league (18324) resolved through
  both. So an empty/null league lookup does **not** mean the id is wrong.
- `league(id:)` returned null for every id tried on a non-admin token
  (18324 included). Prefer `leagues(request: {leagueIds: [...]})`, which does
  work, and whose `matches(request: {take, skip})` pages the match list.
- `leagues(request:)` filters that work: `tiers` (e.g. `[INTERNATIONAL]`
  returns the historical TI ids), `leagueIds`, `betweenStartDateTime`.
  `orderBy: ID` sorts **ascending** (oldest first) — not useful for "newest";
  use `LAST_MATCH_TIME`. Ordering by last match time surfaces mostly AMATEUR
  leagues, so filter by `tiers` when you want pro events.

## Enumerating a tournament the league endpoints don't expose

`player(steamAccountId:).matches(request: {leagueId: <id>, take, skip})`
filters correctly even when the league itself is missing from the league
table. From one known participant, alternate player → their league matches →
those matches' 10 `steamAccountId`s → repeat, until closure. A tournament
bracket is densely connected, so one seed reaches every team (verified: one
seed → exactly 80 players / 16 teams). Working shape:

```graphql
query ($id: Long!, $league: Int!, $take: Int!, $skip: Int!) {
  player(steamAccountId: $id) {
    matches(request: {leagueId: $league, take: $take, skip: $skip}) { id }
  }
}
```

## match — misc field semantics

- `seriesId` groups the games of one Bo3/Bo5. Series winner = the side with
  more game wins; without it, team records are per game and a 2-0 reads as
  two wins.
- League matches report `lobbyType: PRACTICE` — that is the normal value for
  tournament lobbies, not a sign of a scrim.
- `radiantTeam.name` / `direTeam.name` are the org's *registered* team entity,
  which can differ from the name a team competes under at an event (TI alias,
  sponsor-stripped names). Don't expect them to match a bracket page.
- `players[].imp` is benchmarked against the general playerbase, so pro
  players routinely average **negative** IMP even in games they win — it is
  not a "played badly" signal at this tier.
- Stratz ingests a live event with a lag: mid-tournament, the most recent
  days' matches can be simply absent (confirmed by an unfiltered
  `player.matches` list ending at the same date). Check `max(startDateTime)`
  against the real schedule before reading a tournament report as complete.

## Auth

- HTTP 403 with `{"message":"A bearer token is required for a request."}`
  means the token is **invalid or expired**, not that the header is missing.
  Stratz tokens are JWTs — decode the `exp` claim to check before debugging
  the query.

## match.pickBans — draft order and phases

- `order` is a **single global 0..23 sequence** over the whole draft, not
  separate counters for picks and bans. Verified identical across all 138
  games of a captains-mode event — every slot index appears exactly once per
  match and its `isPick` value never varies:

  ```
  slot  0 1 2 3 4 5 6 | 7 8 | 9 10 11 | 12 .. 17 | 18 19 20 21 | 22 23
        B B B B B B B | P P | B  B  B | P  P  P  | B  B  B  B  | P  P
  ```

  14 bans + 10 picks. So ban phases are `order <= 6`, `7..11`, `>= 12`, and
  pick phases are `7-8`, `12-17`, `22-23`.
- `isRadiant` on a slot varies match to match (it follows the first-pick
  coin/choice), so never assume slot 0 belongs to a fixed side.
- Phase splits carry real signal that a raw ban count hides: a hero banned
  almost entirely in phase 1 is a consensus must-remove, while the same total
  spread across phases 2-3 marks a reactive/counter ban.
