"""Hero statistics for BLAST Slam VII (Stratz leagueId 19101).

Runs end-to-end from the cached raw match JSON produced by fetching each of the
102 tournament match ids via the singular `match(id:)` query (the plural
`matches(ids:)` query is admin-gated — see cookbook).

Metrics (grain = hero, denominator = total drafted games):
  picks       = times the hero was on a team's roster (one row per player slot)
  wins        = picks where that player slot won
  win_rate    = wins / picks
  bans        = times the hero was banned (pickBans.isPick = false)
  contest     = picks + bans
  pick_rate   = picks / games
  ban_rate    = bans / games
  contest_rate= contest / games
"""
import json
import sys
import duckdb

RAW = "data/raw/bs7_matches_combined.json"
HEROES = "data/raw/heroes_const.json"

heroes = {h["id"]: h["displayName"] for h in json.load(open(HEROES))}
games = len(json.load(open(RAW))["matches"])

con = duckdb.connect()
con.execute("CREATE TABLE hero_names AS SELECT * FROM (VALUES " +
            ",".join(f"({i},'{n.replace(chr(39), chr(39)*2)}')" for i, n in heroes.items()) +
            ") t(hero_id, hero)")

# Picks & wins, one row per player slot
con.execute(f"""
CREATE TABLE picks AS
SELECT p.heroId AS hero_id,
       count(*) AS picks,
       sum(CASE WHEN p.isVictory THEN 1 ELSE 0 END) AS wins
FROM read_json('{RAW}') t, unnest(t.matches) AS x(m), unnest(m.players) AS y(p)
GROUP BY 1
""")

# Bans: pickBans rows where isPick is false carry bannedHeroId
con.execute(f"""
CREATE TABLE bans AS
SELECT pb.bannedHeroId AS hero_id, count(*) AS bans
FROM read_json('{RAW}') t, unnest(t.matches) AS x(m), unnest(m.pickBans) AS z(pb)
WHERE pb.isPick = false AND pb.bannedHeroId IS NOT NULL
GROUP BY 1
""")

con.execute(f"""
CREATE TABLE hero_stats AS
SELECT n.hero,
       coalesce(p.picks, 0)               AS picks,
       coalesce(p.wins, 0)                AS wins,
       coalesce(b.bans, 0)                AS bans,
       coalesce(p.picks,0)+coalesce(b.bans,0) AS contest,
       round(100.0*p.wins/nullif(p.picks,0), 1)        AS win_pct,
       round(100.0*coalesce(p.picks,0)/{games}, 1)     AS pick_pct,
       round(100.0*coalesce(b.bans,0)/{games}, 1)      AS ban_pct,
       round(100.0*(coalesce(p.picks,0)+coalesce(b.bans,0))/{games}, 1) AS contest_pct
FROM hero_names n
LEFT JOIN picks p ON p.hero_id = n.hero_id
LEFT JOIN bans  b ON b.hero_id = n.hero_id
WHERE coalesce(p.picks,0) + coalesce(b.bans,0) > 0
""")

# Sanity checks
tot = con.execute("SELECT sum(picks), sum(wins) FROM hero_stats").fetchone()
print(f"BLAST Slam VII — leagueId 19101 — {games} matches")
print(f"sanity: total picks={tot[0]} (expect {games*10}), "
      f"total wins={tot[1]} (expect {games*5}, one winner-half per match)\n")

def show(title, order, n=15):
    print(title)
    rows = con.execute(f"""
        SELECT hero, picks, bans, contest, win_pct, pick_pct, ban_pct, contest_pct
        FROM hero_stats ORDER BY {order} LIMIT {n}
    """).fetchall()
    print(f"{'Hero':<22}{'P':>4}{'B':>4}{'Ctst':>6}{'Win%':>7}{'Pick%':>7}{'Ban%':>7}{'Ctst%':>7}")
    for r in rows:
        print(f"{r[0]:<22}{r[1]:>4}{r[2]:>4}{r[3]:>6}{str(r[4]):>7}{str(r[5]):>7}{str(r[6]):>7}{str(r[7]):>7}")
    print()

show("== Most contested (picks + bans) ==", "contest DESC, picks DESC")
show("== Most picked ==", "picks DESC, win_pct DESC")
show("== Most banned ==", "bans DESC, picks DESC")
show("== Best win rate (min 5 picks) ==",
     "CASE WHEN picks>=5 THEN win_pct ELSE -1 END DESC, picks DESC")
show("== Worst win rate (min 5 picks) ==",
     "CASE WHEN picks>=5 THEN win_pct ELSE 999 END ASC, picks DESC")
