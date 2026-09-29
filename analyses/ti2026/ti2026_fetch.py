"""Fetch every The International 2026 match (Stratz leagueId 19719) to data/raw/.

TI 2026 / TI15 — Shanghai, 2026-08-13..08-23, patch 7.41e, 16 teams
(Swiss group stage + elimination round + double-elim playoffs).

Why a crawl rather than a league listing: Stratz has the *matches* under
leagueId 19719, but its league table does not expose the league itself —
`league(id: 19719)` is null and `leagues(request: {leagueIds: [19719]})` is
empty (TI 2025, id 18324, resolves fine both ways). So the only way in is
`player(steamAccountId:).matches(request: {leagueId: 19719})`, which does
filter correctly. Starting from one known participant we alternate:

    player -> their league-19719 match ids -> those matches' 10 players -> ...

until closure. A Swiss bracket is densely connected, so one seed reaches all
16 teams. The plural `matches(ids:)` query is admin-gated (see cookbook), so
matches are fetched one id at a time — long TTL, since a finished match never
changes.

Output: data/raw/ti2026_matches_combined.json -> {"leagueId":…, "matches":[…]}

    uv run analyses/ti2026/ti2026_fetch.py [--refresh]

--refresh re-walks the per-player match lists (use while the event is live to
pick up new games); already-fetched matches stay served from cache.

Provenance: ti2026.context.json.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / ".claude" / "skills" / "stratz-analysis" / "scripts"))

from client import fetch  # noqa: E402

LEAGUE_ID = 19719
SEED_STEAM_IDS = [898754153]  # Ame (Xtreme Gaming) — any participant closes the graph
PAGE = 50
OUT = REPO_ROOT / "data" / "raw" / "ti2026_matches_combined.json"

PLAYER_MATCHES_QUERY = """
query ($id: Long!, $league: Int!, $take: Int!, $skip: Int!) {
  player(steamAccountId: $id) {
    matches(request: {leagueId: $league, take: $take, skip: $skip}) { id }
  }
}
"""

MATCH_QUERY = """
query ($id: Long!) {
  match(id: $id) {
    id didRadiantWin leagueId seriesId gameVersionId durationSeconds startDateTime
    radiantTeamId direTeamId
    radiantTeam { id name }
    direTeam { id name }
    players {
      steamAccountId heroId isRadiant isVictory position lane role
      kills deaths assists networth goldPerMinute experiencePerMinute
      numLastHits numDenies heroDamage towerDamage imp
      steamAccount { name proSteamAccount { name teamId } }
    }
    pickBans { isPick heroId bannedHeroId isRadiant order }
  }
}
"""


def player_match_ids(steam_id: int, ttl_days: float) -> list[int]:
    ids, skip = [], 0
    while True:
        player = fetch(
            PLAYER_MATCHES_QUERY,
            {"id": steam_id, "league": LEAGUE_ID, "take": PAGE, "skip": skip},
            ttl_days=ttl_days,
        )["player"]
        page = (player or {}).get("matches") or []
        ids += [m["id"] for m in page]
        if len(page) < PAGE:
            return ids
        skip += PAGE


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true",
                    help="re-walk player match lists instead of using the cached walk")
    args = ap.parse_args()
    list_ttl = 0 if args.refresh else 0.25

    matches: dict[int, dict] = {}
    seen_players: set[int] = set()
    player_queue: list[int] = list(SEED_STEAM_IDS)

    while player_queue:
        steam_id = player_queue.pop()
        if steam_id in seen_players:
            continue
        seen_players.add(steam_id)

        for match_id in player_match_ids(steam_id, list_ttl):
            if match_id in matches:
                continue
            match = fetch(MATCH_QUERY, {"id": match_id}, ttl_days=3650)["match"]
            if not match or match.get("leagueId") != LEAGUE_ID:
                continue
            matches[match_id] = match
            for p in match["players"]:
                if p["steamAccountId"] and p["steamAccountId"] not in seen_players:
                    player_queue.append(p["steamAccountId"])

        print(f"  players {len(seen_players)} (+{len(player_queue)} queued) | "
              f"matches {len(matches)}")

    ordered = [matches[k] for k in sorted(matches)]
    OUT.write_text(json.dumps({"leagueId": LEAGUE_ID, "matches": ordered}))
    print(f"wrote {len(ordered)} matches, {len(seen_players)} players "
          f"-> {OUT.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
