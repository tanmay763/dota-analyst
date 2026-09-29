"""Hero-pool scouting data for any TI 2026 team(s), for the draft-board artifact.

Runs from the raw cache produced by analyses/ti2026/ti2026_fetch.py. Grain = one row
per player per hero, results in chronological order so the board can show form.
With exactly two teams, also computes the contested pool — both overall and
scoped to each position — plus the ban side of contest: how often each team
removes a hero, and how often opponents removed it from them. A hero both sides
ban every game is contested even though it never appears in a pick table, so a
pick-only view of "contested" systematically misses the highest-priority heroes.

Each hero is assigned the position it was most played at across the whole
tournament (not just by these two teams), so banned-only heroes still land in a
role. Heroes whose modal position holds less than 60% of their games are marked
flex — the single position is a weaker claim for them.

For two teams it also scores a first-phase ban prediction — a transparent
blend, not a model, with the components kept on every row.

Without --series: 45% tournament-wide first-phase ban rate, 35% the banning
team's own first-phase rate, 20% opponent threat (how often the opponent drafts
it, weighted by their results on it).

With --series: the head-to-head itself dominates at 40%, because base rate is
what misleads in a specific matchup. Scored against the TI15 final, the
tournament-weighted version caught the consensus bans (Treant, Earth Spirit,
Keeper of the Light) but missed the ones that decided the series — Bounty
Hunter, first-phase banned by Spirit in all four games on a 15% base rate, and
PARIVISION's Winter Wyvern and Clockwerk. Low base rate plus high in-series
frequency is exactly the signal a tournament prior washes out.

    uv run analyses/ti2026/ti2026_scouting.py --teams PARIVISION \
        -o analyses/ti2026/out/pari_scouting_YYYY-MM-DD.json
    uv run analyses/ti2026/ti2026_scouting.py --teams "Team Spirit" "BetBoom Team" \
        --aliases "BetBoom Team=BoomBoys" -o analyses/ti2026/out/lb_scouting_YYYY-MM-DD.json

Stratz reports the registered org name, which can differ from the name a team
competes under at TI — pass --aliases NAME=ALIAS to label those.

Provenance: ti2026.context.json.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import duckdb

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW = REPO_ROOT / "data" / "raw" / "ti2026_matches_combined.json"
HEROES = REPO_ROOT / "data" / "raw" / "heroes_const.json"

ap = argparse.ArgumentParser()
ap.add_argument("--teams", nargs="+", default=["PARIVISION"])
ap.add_argument("--aliases", nargs="*", default=[], help="STRATZ_NAME=EVENT_ALIAS")
ap.add_argument("--series", type=int, default=None,
                help="seriesId of the head-to-head so far; makes prediction series-aware")
ap.add_argument("-o", "--out", default=str(Path(__file__).parent / "out" / "scouting.json"))
args = ap.parse_args()

aliases = dict(a.split("=", 1) for a in args.aliases)

heroes = {h["id"]: h["displayName"] for h in json.loads(HEROES.read_text())}
con = duckdb.connect()
con.execute(f"CREATE TABLE m AS SELECT unnest(matches) AS m FROM read_json('{RAW}')")
con.execute(
    "CREATE TABLE hn AS SELECT * FROM (VALUES "
    + ",".join(f"({i},'{n.replace(chr(39), chr(39) * 2)}')" for i, n in heroes.items())
    + ") t(hid, hero)"
)
con.execute("""
CREATE TABLE pl AS
SELECT regexp_replace(coalesce(p.steamAccount.proSteamAccount.name, ''),
                      '^\\s+|\\s+$', '', 'g') AS player,
       p.position AS pos, hn.hero, p.isVictory AS won, m.startDateTime AS st,
       p.kills AS k, p.deaths AS d, p.assists AS a,
       p.goldPerMinute AS gpm, p.imp,
       CASE WHEN p.isRadiant THEN m.radiantTeam.name ELSE m.direTeam.name END AS team
FROM m, unnest(m.players) AS y(p) JOIN hn ON hn.hid = p.heroId
""")


con.execute("""
CREATE TABLE bans AS
SELECT hn.hero,
       CASE WHEN pb."order" <= 6 THEN 1 WHEN pb."order" <= 11 THEN 2 ELSE 3 END AS phase,
       CASE WHEN pb.isRadiant THEN m.radiantTeam.name ELSE m.direTeam.name END AS banner,
       CASE WHEN pb.isRadiant THEN m.direTeam.name ELSE m.radiantTeam.name END AS victim
FROM m, unnest(m.pickBans) AS z(pb) JOIN hn ON hn.hid = pb.bannedHeroId
WHERE pb.isPick = false
""")


def team_block(team: str) -> dict:
    games = con.execute(
        "SELECT count(*) FROM m WHERE m.radiantTeam.name = ? OR m.direTeam.name = ?",
        [team, team]).fetchone()[0]
    wins = con.execute("""
        SELECT count(*) FROM m WHERE (m.radiantTeam.name = ? AND m.didRadiantWin)
           OR (m.direTeam.name = ? AND NOT m.didRadiantWin)""", [team, team]).fetchone()[0]

    players = []
    for player, pos, n, w, gpm, imp in con.execute("""
        SELECT player, any_value(pos), count(*), sum(won::int), round(avg(gpm)), round(avg(imp), 1)
        FROM pl WHERE team = ? GROUP BY 1 ORDER BY any_value(pos)""", [team]).fetchall():
        pool = con.execute("""
            SELECT hero, count(*), sum(won::int), round(avg(gpm)),
                   round(avg(k), 1), round(avg(d), 1), round(avg(a), 1), list(won ORDER BY st)
            FROM pl WHERE team = ? AND player = ?
            GROUP BY 1 ORDER BY count(*) DESC, sum(won::int) DESC, hero""",
            [team, player]).fetchall()
        players.append({
            "player": player, "pos": int(pos.replace("POSITION_", "")),
            "games": n, "wins": int(w), "gpm": int(gpm), "imp": float(imp),
            "heroes": [{"hero": h, "n": c, "w": int(ww), "gpm": int(g),
                        "k": kk, "d": dd, "a": aa, "form": [bool(x) for x in f]}
                       for h, c, ww, g, kk, dd, aa, f in pool],
        })
    return {"team": team, "alias": aliases.get(team), "games": games,
            "wins": wins, "losses": games - wins, "players": players}


blocks = [team_block(t) for t in args.teams]

contested: list[dict] = []
contested_by_pos: dict[str, list[dict]] = {}
contest_index: list[dict] = []
contest_by_pos: dict[str, list[dict]] = {}
if len(args.teams) == 2:
    a, b = args.teams

    # bans[hero] = (banned by A, banned by B, banned against A, banned against B)
    ban_map = {
        h: (int(ab), int(bb), int(ad), int(bd))
        for h, ab, bb, ad, bd in con.execute("""
            SELECT hero, sum((banner = ?)::int), sum((banner = ?)::int),
                         sum((victim = ?)::int), sum((victim = ?)::int)
            FROM bans GROUP BY 1""", [a, b, a, b]).fetchall()
    }

    def with_bans(rows: list[dict]) -> list[dict]:
        for r in rows:
            ab, bb, ad, bd = ban_map.get(r["hero"], (0, 0, 0, 0))
            r.update(a_ban=ab, b_ban=bb, a_denied=ad, b_denied=bd)
        return rows

    def overlap(pos: str | None) -> list[dict]:
        """Heroes both sides drafted; scoped to one position when pos is given."""
        clause = "AND pos = ?" if pos else ""
        params = [a, b] + ([pos] if pos else []) + [a, a, b, b, a, b]
        return with_bans([
            {"hero": h, "a_n": an, "a_w": int(aw), "b_n": bn, "b_w": int(bw)}
            for h, an, aw, bn, bw in con.execute(f"""
                WITH t AS (SELECT hero, team, count(*) n, sum(won::int) w
                           FROM pl WHERE team IN (?, ?) {clause} GROUP BY 1, 2)
                SELECT hero,
                       max(CASE WHEN team = ? THEN n END), max(CASE WHEN team = ? THEN w END),
                       max(CASE WHEN team = ? THEN n END), max(CASE WHEN team = ? THEN w END)
                FROM t GROUP BY 1 HAVING count(*) = 2
                ORDER BY (max(CASE WHEN team = ? THEN n END)
                        + max(CASE WHEN team = ? THEN n END)) DESC, hero""", params).fetchall()
        ])

    contested = overlap(None)
    contested_by_pos = {str(i): overlap(f"POSITION_{i}") for i in range(1, 6)}

    # Holistic contest: every hero either finalist has picked OR banned, ranked by
    # total engagement. This is the view that surfaces heroes banned out every game.
    picks_map = {
        h: (int(an), int(aw), int(bn), int(bw))
        for h, an, aw, bn, bw in con.execute("""
            SELECT hero, sum((team = ?)::int), sum(((team = ?) AND won)::int),
                         sum((team = ?)::int), sum(((team = ?) AND won)::int)
            FROM pl WHERE team IN (?, ?) GROUP BY 1""", [a, a, b, b, a, b]).fetchall()
    }
    for hero in set(picks_map) | set(ban_map):
        an, aw, bn, bw = picks_map.get(hero, (0, 0, 0, 0))
        ab, bb, ad, bd = ban_map.get(hero, (0, 0, 0, 0))
        if an + bn + ab + bb == 0:
            continue
        contest_index.append({
            "hero": hero, "a_n": an, "a_w": aw, "b_n": bn, "b_w": bw,
            "a_ban": ab, "b_ban": bb, "a_denied": ad, "b_denied": bd,
            "picks": an + bn, "bans": ab + bb, "contest": an + bn + ab + bb,
        })
    # Canonical position = modal position across every pick in the tournament.
    hero_pos = {
        h: (int(pos.replace("POSITION_", "")), n, share)
        for h, pos, n, share in con.execute("""
            WITH c AS (SELECT hero, pos, count(*) n FROM pl GROUP BY 1, 2),
                 t AS (SELECT hero, sum(n) tot FROM c GROUP BY 1)
            SELECT c.hero, c.pos, c.n, c.n::double / t.tot
            FROM c JOIN t ON t.hero = c.hero
            QUALIFY row_number() OVER (PARTITION BY c.hero ORDER BY c.n DESC, c.pos) = 1
        """).fetchall()
    }
    for r in contest_index:
        pos, n, share = hero_pos.get(r["hero"], (None, 0, 0.0))
        r["pos"] = pos
        r["pos_games"] = n
        r["flex"] = bool(pos) and share < 0.6
    contest_index.sort(key=lambda r: (-r["contest"], -r["bans"], r["hero"]))
    contest_by_pos = {
        str(i): [r for r in contest_index if r["pos"] == i] for i in range(1, 6)
    }
    contest_by_pos["none"] = [r for r in contest_index if r["pos"] is None]

predictions: dict = {}
if len(args.teams) == 2:
    total_games = con.execute("SELECT count(*) FROM m").fetchone()[0]
    p1 = {
        h: (int(n), int(pn), int(sn))
        for h, n, pn, sn in con.execute("""
            SELECT hero, count(*), sum((banner = ?)::int), sum((banner = ?)::int)
            FROM bans WHERE phase = 1 GROUP BY 1""", [a, b]).fetchall()
    }
    games_of = {t["team"]: t["games"] for t in blocks}

    # In-series first-phase bans: the strongest available signal for the next game.
    series_games, series_p1 = 0, {}
    if args.series is not None:
        series_games = con.execute(
            "SELECT count(*) FROM m WHERE m.seriesId = ?", [args.series]).fetchone()[0]
        series_p1 = {
            (h, t): int(n)
            for h, t, n in con.execute("""
                SELECT hn.hero,
                       CASE WHEN pb.isRadiant THEN m.radiantTeam.name ELSE m.direTeam.name END,
                       count(*)
                FROM m, unnest(m.pickBans) AS z(pb) JOIN hn ON hn.hid = pb.bannedHeroId
                WHERE pb.isPick = false AND pb."order" <= 6 AND m.seriesId = ?
                GROUP BY 1, 2""", [args.series]).fetchall()
        }
    picks_of = {
        (h, t): (int(n), int(w))
        for h, t, n, w in con.execute("""
            SELECT hero, team, count(*), sum(won::int) FROM pl
            WHERE team IN (?, ?) GROUP BY 1, 2""", [a, b]).fetchall()
    }

    def score_for(banner: str, opponent: str) -> list[dict]:
        rows = []
        universe = set(p1) | {h for (h, t) in series_p1 if t == banner}
        for hero in universe:
            n_all, pn, sn = p1.get(hero, (0, 0, 0))
            base = n_all / total_games
            own = (pn if banner == a else sn) / games_of[banner]
            opp_n, opp_w = picks_of.get((hero, opponent), (0, 0))
            opp_rate = opp_n / games_of[opponent]
            opp_wr = (opp_w / opp_n) if opp_n else 0.5
            threat = min(1.0, opp_rate * (0.5 + opp_wr))
            own = min(1.0, own)
            in_series = (series_p1.get((hero, banner), 0) / series_games) if series_games else 0.0
            if series_games:
                score = 0.40 * in_series + 0.25 * base + 0.20 * own + 0.15 * threat
            else:
                score = 0.45 * base + 0.35 * own + 0.20 * threat
            rows.append({
                "hero": hero, "base": round(base, 3), "own": round(own, 3),
                "threat": round(threat, 3), "opp_n": opp_n, "opp_w": opp_w,
                "series": round(in_series, 3),
                "series_n": series_p1.get((hero, banner), 0),
                "score": round(score, 4),
            })
        rows.sort(key=lambda r: -r["score"])
        return rows[:8]

    predictions = {
        "weights": ({"in_series": 0.40, "tournament_rate": 0.25, "own_rate": 0.20,
                     "opponent_threat": 0.15} if series_games else
                    {"tournament_rate": 0.45, "own_rate": 0.35, "opponent_threat": 0.20}),
        "series_games": series_games,
        "first_phase": {a: score_for(a, b), b: score_for(b, a)},
        "slots": 7,
    }

span = con.execute("""
    SELECT strftime(to_timestamp(min(m.startDateTime)), '%b %-d'),
           strftime(to_timestamp(max(m.startDateTime)), '%b %-d'), count(*) FROM m""").fetchone()

Path(args.out).write_text(json.dumps(
    {"teams": blocks, "contested": contested, "contested_by_pos": contested_by_pos,
     "contest_index": contest_index,
     "contest_by_pos": contest_by_pos if len(args.teams) == 2 else {},
     "predictions": predictions,
     "coverage": {"from": span[0], "to": span[1], "tournament_games": span[2]}}, indent=1))
for blk in blocks:
    print(f"{blk['team']}: {blk['wins']}-{blk['losses']} over {blk['games']} games")
print(f"contested heroes: {len(contested)} -> {args.out}")
