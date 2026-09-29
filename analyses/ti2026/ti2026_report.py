"""The International 2026 (Stratz leagueId 19719) — hero, team and player report.

Runs end-to-end from the raw cache produced by `analyses/ti2026/ti2026_fetch.py`.

    uv run analyses/ti2026/ti2026_fetch.py     # populates data/raw/
    uv run analyses/ti2026/ti2026_report.py

Grain and denominators (games = drafted matches in the cache):
  HEROES  picks   = hero on a team's roster (one row per player slot)
          wins    = picks whose slot won
          bans    = pickBans rows with isPick = false (hero in bannedHeroId),
                    split by draft phase off `order` (see BAN_PHASE)
          contest = picks + bans;  *_pct are all over `games`
  TEAMS   both series records (grouped on seriesId, winner = more game wins)
          and per-game records
  PLAYERS one row per player slot, keyed on steamAccountId

Provenance: ti2026.context.json.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import duckdb

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW = REPO_ROOT / "data" / "raw" / "ti2026_matches_combined.json"
HEROES = REPO_ROOT / "data" / "raw" / "heroes_const.json"

sys.path.insert(0, str(REPO_ROOT / ".claude" / "skills" / "stratz-analysis" / "scripts"))
from client import fetch  # noqa: E402

if not RAW.exists():
    sys.exit(f"{RAW} missing — run: uv run analyses/ti2026/ti2026_fetch.py")

payload = json.loads(RAW.read_text())
games = len(payload["matches"])
league = payload.get("league") or {}

if HEROES.exists():
    heroes = {h["id"]: h["displayName"] for h in json.loads(HEROES.read_text())}
else:
    heroes = {
        h["id"]: h["displayName"]
        for h in fetch("query { constants { heroes { id displayName } } }", ttl_days=3650)[
            "constants"
        ]["heroes"]
    }

con = duckdb.connect()
con.execute(
    "CREATE TABLE hero_names AS SELECT * FROM (VALUES "
    + ",".join(f"({i},'{n.replace(chr(39), chr(39) * 2)}')" for i, n in heroes.items())
    + ") t(hero_id, hero)"
)
con.execute(f"CREATE TABLE m AS SELECT unnest(matches) AS m FROM read_json('{RAW}')")

# ---------------------------------------------------------------- heroes
con.execute("""
CREATE TABLE picks AS
SELECT p.heroId AS hero_id,
       count(*) AS picks,
       sum(CASE WHEN p.isVictory THEN 1 ELSE 0 END) AS wins
FROM m, unnest(m.players) AS y(p)
GROUP BY 1
""")

con.execute("""
CREATE TABLE bans AS
SELECT pb.bannedHeroId AS hero_id, count(*) AS bans
FROM m, unnest(m.pickBans) AS z(pb)
WHERE pb.isPick = false AND pb.bannedHeroId IS NOT NULL
GROUP BY 1
""")

con.execute(f"""
CREATE TABLE hero_stats AS
SELECT n.hero,
       coalesce(p.picks, 0) AS picks,
       coalesce(p.wins, 0)  AS wins,
       coalesce(b.bans, 0)  AS bans,
       coalesce(p.picks, 0) + coalesce(b.bans, 0) AS contest,
       round(100.0 * p.wins / nullif(p.picks, 0), 1)                          AS win_pct,
       round(100.0 * coalesce(p.picks, 0) / {games}, 1)                       AS pick_pct,
       round(100.0 * coalesce(b.bans, 0) / {games}, 1)                        AS ban_pct,
       round(100.0 * (coalesce(p.picks, 0) + coalesce(b.bans, 0)) / {games}, 1) AS contest_pct
FROM hero_names n
LEFT JOIN picks p ON p.hero_id = n.hero_id
LEFT JOIN bans  b ON b.hero_id = n.hero_id
WHERE coalesce(p.picks, 0) + coalesce(b.bans, 0) > 0
""")

# ------------------------------------------------------- bans by draft phase
# Captains Mode draft is a fixed 24-slot sequence, identical in every game:
#   0-6 ban | 7-8 pick | 9-11 ban | 12-17 pick | 18-21 ban | 22-23 pick
BAN_PHASE = "CASE WHEN pb.\"order\" <= 6 THEN 1 WHEN pb.\"order\" <= 11 THEN 2 ELSE 3 END"

con.execute(f"""
CREATE TABLE ban_phase AS
SELECT pb.bannedHeroId AS hero_id, {BAN_PHASE} AS phase
FROM m, unnest(m.pickBans) AS z(pb)
WHERE pb.isPick = false AND pb.bannedHeroId IS NOT NULL
""")

con.execute("""
CREATE TABLE hero_ban_phase AS
SELECT n.hero,
       count(*) AS bans,
       sum((b.phase = 1)::int) AS p1,
       sum((b.phase = 2)::int) AS p2,
       sum((b.phase = 3)::int) AS p3,
       round(100.0 * sum((b.phase = 1)::int) / count(*)) AS pct_p1
FROM ban_phase b JOIN hero_names n ON n.hero_id = b.hero_id
GROUP BY 1
""")

# ---------------------------------------------------------------- teams
con.execute("""
CREATE TABLE team_games AS
SELECT coalesce(m.radiantTeam.name, 'team ' || m.radiantTeamId) AS team,
       m.didRadiantWin AS won, true AS radiant, m.durationSeconds AS secs,
       m.seriesId AS series_id, m.startDateTime AS start_dt
FROM m
UNION ALL
SELECT coalesce(m.direTeam.name, 'team ' || m.direTeamId),
       NOT m.didRadiantWin, false, m.durationSeconds, m.seriesId, m.startDateTime
FROM m
""")

# A series is won by whichever side took more games in it.
con.execute("""
CREATE TABLE team_series AS
WITH per_series AS (
    SELECT team, series_id,
           sum(CASE WHEN won THEN 1 ELSE 0 END) AS gw,
           count(*) - sum(CASE WHEN won THEN 1 ELSE 0 END) AS gl
    FROM team_games WHERE series_id IS NOT NULL GROUP BY 1, 2
)
SELECT team,
       count(*) AS series,
       sum(CASE WHEN gw > gl THEN 1 ELSE 0 END) AS s_wins,
       sum(CASE WHEN gw < gl THEN 1 ELSE 0 END) AS s_losses
FROM per_series GROUP BY 1
""")

con.execute("""
CREATE TABLE team_stats AS
SELECT g.team,
       s.series, s.s_wins, s.s_losses,
       count(*) AS games,
       sum(CASE WHEN g.won THEN 1 ELSE 0 END) AS wins,
       count(*) - sum(CASE WHEN g.won THEN 1 ELSE 0 END) AS losses,
       round(100.0 * sum(CASE WHEN g.won THEN 1 ELSE 0 END) / count(*), 1) AS win_pct,
       sum(CASE WHEN g.radiant AND g.won THEN 1 ELSE 0 END) AS radiant_wins,
       sum(CASE WHEN g.radiant THEN 1 ELSE 0 END) AS radiant_games,
       round(avg(g.secs) / 60.0, 1) AS avg_min
FROM team_games g LEFT JOIN team_series s ON s.team = g.team
GROUP BY 1, 2, 3, 4
""")

# ---------------------------------------------------------------- players
con.execute("""
CREATE TABLE player_stats AS
SELECT regexp_replace(coalesce(p.steamAccount.proSteamAccount.name,
                                p.steamAccount.name, 'id ' || p.steamAccountId),
                       '^\\s+|\\s+$', '', 'g') AS player,
       any_value(p.position) AS pos,
       count(*) AS games,
       sum(CASE WHEN p.isVictory THEN 1 ELSE 0 END) AS wins,
       round(100.0 * sum(CASE WHEN p.isVictory THEN 1 ELSE 0 END) / count(*), 1) AS win_pct,
       round(avg(p.kills), 1)   AS k,
       round(avg(p.deaths), 1)  AS d,
       round(avg(p.assists), 1) AS a,
       round((sum(p.kills) + sum(p.assists)) / nullif(sum(p.deaths), 0), 2) AS kda,
       round(avg(p.goldPerMinute))  AS gpm,
       round(avg(p.experiencePerMinute)) AS xpm,
       round(avg(p.imp), 1) AS imp,
       count(DISTINCT p.heroId) AS heroes
FROM m, unnest(m.players) AS y(p)
GROUP BY 1
""")


def table(title, sql, headers, widths):
    print(title)
    rows = con.execute(sql).fetchall()
    print("".join(f"{h:{'<' if i == 0 else '>'}{w}}" for i, (h, w) in enumerate(zip(headers, widths))))
    for r in rows:
        print("".join(
            f"{('' if v is None else v):{'<' if i == 0 else '>'}{w}}"
            for i, (v, w) in enumerate(zip([str(x) if x is not None else '-' for x in r], widths))
        ))
    print()


name = league.get("displayName") or "The International 2026"
print(f"{name} — leagueId {payload['leagueId']} — {games} matches")
tot = con.execute("SELECT sum(picks), sum(wins) FROM hero_stats").fetchone()
print(f"sanity: picks={tot[0]} (expect {games * 10}), wins={tot[1]} (expect {games * 5})")
print(f"heroes drafted or banned: "
      f"{con.execute('SELECT count(*) FROM hero_stats').fetchone()[0]} of {len(heroes)}")

span = con.execute("""
    SELECT strftime(to_timestamp(min(m.startDateTime)), '%Y-%m-%d'),
           strftime(to_timestamp(max(m.startDateTime)), '%Y-%m-%d'),
           count(DISTINCT m.seriesId),
           round(100.0 * sum(CASE WHEN m.didRadiantWin THEN 1 ELSE 0 END) / count(*), 1),
           round(avg(m.durationSeconds) / 60.0, 1),
           round(min(m.durationSeconds) / 60.0, 1),
           round(max(m.durationSeconds) / 60.0, 1)
    FROM m
""").fetchone()
print(f"coverage: {span[0]} .. {span[1]}  ({span[2]} series)")
print(f"radiant win rate {span[3]}%  |  duration avg {span[4]} min "
      f"(min {span[5]}, max {span[6]})\n")

HERO_COLS = "hero, picks, bans, contest, win_pct, pick_pct, ban_pct, contest_pct"
HERO_HEAD = ["Hero", "P", "B", "Ctst", "Win%", "Pick%", "Ban%", "Ctst%"]
HERO_W = [22, 4, 4, 6, 7, 7, 7, 7]

for title, order in [
    ("== Most contested (picks + bans) ==", "contest DESC, picks DESC"),
    ("== Most picked ==", "picks DESC, win_pct DESC"),
    ("== Most banned ==", "bans DESC, picks DESC"),
    ("== Best win rate (min 5 picks) ==",
     "CASE WHEN picks >= 5 THEN win_pct ELSE -1 END DESC, picks DESC"),
    ("== Worst win rate (min 5 picks) ==",
     "CASE WHEN picks >= 5 THEN win_pct ELSE 999 END ASC, picks DESC"),
]:
    table(title, f"SELECT {HERO_COLS} FROM hero_stats ORDER BY {order} LIMIT 15",
          HERO_HEAD, HERO_W)

print("== Bans by draft phase (1 = slots 0-6, 2 = 9-11, 3 = 18-21) ==")
for ph, n_bans, n_heroes in con.execute(
    "SELECT phase, count(*), count(DISTINCT hero_id) FROM ban_phase GROUP BY 1 ORDER BY 1"
).fetchall():
    print(f"  phase {ph}: {n_bans} bans across {n_heroes} distinct heroes")
print()

for ph in (1, 2, 3):
    table(f"== Most banned — phase {ph} ==",
          f"SELECT n.hero, count(*), round(100.0 * count(*) / {games}, 1) "
          f"FROM ban_phase b JOIN hero_names n ON n.hero_id = b.hero_id "
          f"WHERE b.phase = {ph} GROUP BY 1 ORDER BY 2 DESC LIMIT 10",
          ["Hero", "Bans", "% games"], [22, 6, 9])

table("== Ban timing — where each hero gets removed ==",
      "SELECT hero, bans, p1, p2, p3, pct_p1 FROM hero_ban_phase "
      "ORDER BY bans DESC LIMIT 18",
      ["Hero", "Bans", "P1", "P2", "P3", "%P1"], [22, 6, 5, 5, 5, 6])

table("== Teams — series and game records ==",
      "SELECT team, s_wins || '-' || s_losses, games, wins, losses, win_pct, "
      "radiant_wins || '/' || radiant_games, avg_min "
      "FROM team_stats ORDER BY s_wins DESC, win_pct DESC",
      ["Team", "Series", "G", "W", "L", "Win%", "Rad W/G", "AvgMin"],
      [18, 8, 4, 4, 4, 7, 9, 8])

table("== Players — best win rate (min 5 games) ==",
      "SELECT player, games, wins, win_pct, k, d, a, kda, gpm, imp, heroes "
      "FROM player_stats WHERE games >= 5 ORDER BY win_pct DESC, games DESC LIMIT 20",
      ["Player", "G", "W", "Win%", "K", "D", "A", "KDA", "GPM", "IMP", "Hs"],
      [18, 4, 4, 7, 6, 6, 6, 8, 8, 8, 4])

table("== Players — highest IMP (min 5 games) ==",
      "SELECT player, games, win_pct, kda, gpm, xpm, imp, heroes "
      "FROM player_stats WHERE games >= 5 ORDER BY imp DESC LIMIT 20",
      ["Player", "G", "Win%", "KDA", "GPM", "XPM", "IMP", "Hs"],
      [18, 4, 7, 8, 8, 8, 8, 4])
