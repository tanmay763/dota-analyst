"""Weekly hero win rates by bracket (ALL_PICK_RANKED).

Validation analysis for the stratz-analysis skill loop: fetches the last 8
weeks of heroStats.winWeek for every rank bracket, flattens to parquet, checks
the match-weighted mean win rate ≈ 50% per bracket, and prints the top 5
heroes by win rate per bracket for the latest complete week (hero-week cells
with matchCount < 200 suppressed).

Run from the repo root: uv run analyses/weekly_winrates_by_bracket/weekly_winrates_by_bracket.py
Provenance: weekly_winrates_by_bracket.context.json.
"""

import sys
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / ".claude/skills/stratz-analysis/scripts"))
from client import cache_path, fetch  # noqa: E402

BRACKETS = [
    "HERALD", "GUARDIAN", "CRUSADER", "ARCHON",
    "LEGEND", "ANCIENT", "DIVINE", "IMMORTAL",
]
WEEKS = 8
MIN_MATCHES = 200  # suppress hero-week cells below this sample size

WIN_WEEK_QUERY = """
query ($bracket: [RankBracket], $weeks: Int) {
  heroStats {
    winWeek(take: $weeks, bracketIds: $bracket, gameModeIds: [ALL_PICK_RANKED]) {
      week heroId matchCount winCount
    }
  }
}
"""

HEROES_QUERY = "query { constants { heroes { id displayName } } }"


def main() -> None:
    raw_paths = {}
    for bracket in BRACKETS:
        variables = {"bracket": [bracket], "weeks": WEEKS}
        fetch(WIN_WEEK_QUERY, variables)
        raw_paths[bracket] = cache_path(WIN_WEEK_QUERY, variables)
    fetch(HEROES_QUERY)

    flat_dir = REPO / "data" / "flattened"
    flat_dir.mkdir(parents=True, exist_ok=True)
    win_week_pq = flat_dir / "win_week_by_bracket.parquet"
    heroes_pq = flat_dir / "heroes.parquet"

    union = " UNION ALL ".join(
        f"SELECT '{b}' AS bracket, unnest(heroStats.winWeek, recursive := true) "
        f"FROM read_json('{raw_paths[b]}')"
        for b in BRACKETS
    )
    duckdb.sql(f"COPY ({union}) TO '{win_week_pq}'")
    duckdb.sql(
        f"COPY (SELECT unnest(constants.heroes, recursive := true) "
        f"FROM read_json('{cache_path(HEROES_QUERY)}')) TO '{heroes_pq}'"
    )

    con = duckdb.connect()
    con.sql(f"CREATE VIEW ww AS SELECT * FROM '{win_week_pq}'")
    con.sql(f"CREATE VIEW heroes AS SELECT * FROM '{heroes_pq}'")

    # A week starting at T is complete once now >= T + 7 days.
    latest_complete = con.sql(
        "SELECT max(week) FROM ww WHERE week + 7*86400 <= epoch(now())"
    ).fetchone()[0]
    week_label = con.sql(
        f"SELECT strftime(to_timestamp({latest_complete}), '%Y-%m-%d')"
    ).fetchone()[0]
    print(
        f"Latest complete week starting: {week_label} "
        f"(window: last {WEEKS} weeks, ALL_PICK_RANKED)\n"
    )

    print("Sanity — match-weighted mean win rate per bracket (expect ≈ 0.5):")
    sanity = con.sql("""
        SELECT bracket,
               sum(matchCount) AS hero_slots,
               round(sum(winCount) / sum(matchCount), 4) AS weighted_wr
        FROM ww GROUP BY bracket
        ORDER BY array_position(['HERALD','GUARDIAN','CRUSADER','ARCHON',
                                 'LEGEND','ANCIENT','DIVINE','IMMORTAL'], bracket)
    """)
    sanity.show()
    bad = [r for r in sanity.fetchall() if abs(r[2] - 0.5) > 0.01]
    assert not bad, f"sanity check failed for brackets: {bad}"

    print(f"Top 5 heroes by win rate per bracket, week of {week_label} "
          f"(cells with matchCount < {MIN_MATCHES} suppressed):")
    con.sql(f"""
        SELECT ww.bracket,
               row_number() OVER (PARTITION BY ww.bracket
                                  ORDER BY winCount / matchCount DESC) AS rank,
               heroes.displayName AS hero,
               round(winCount / matchCount, 3) AS win_rate,
               matchCount AS matches
        FROM ww JOIN heroes ON ww.heroId = heroes.id
        WHERE week = {latest_complete} AND matchCount >= {MIN_MATCHES}
        QUALIFY rank <= 5
        ORDER BY array_position(['HERALD','GUARDIAN','CRUSADER','ARCHON',
                                 'LEGEND','ANCIENT','DIVINE','IMMORTAL'], ww.bracket),
                 rank
    """).show(max_rows=50)


if __name__ == "__main__":
    main()
