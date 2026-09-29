# BLAST Slam VII hero picks, bans and win rates, 2026-09-29

A dated snapshot of one run of [`blast_slam_vii.py`](blast_slam_vii.py), not maintained
policy. What's known about the request and scope is in
[`blast_slam_vii.context.json`](blast_slam_vii.context.json). The original prompt is lost,
so the question below is inferred.

Question: which heroes were picked, banned and contested most at BLAST Slam VII, and
which won most and least?

| | |
| --- | --- |
| Data | Stratz leagueId 19101: 102 matches cached in `data/raw/bs7_matches_combined.json` (2026-06-11) |
| Run | 2026-09-29, a rerun from that cache. It reproduces the original 2026-06-11 figures, for which no report was saved |
| Measures | Picks and wins per player slot; bans from `pickBans` (`isPick = false`); contest = picks + bans; every rate is over 102 games |
| Sanity | 1,020 picks (10 per game) and 510 wins (5 per game) |
| Rerun | `uv run analyses/blast_slam_vii/blast_slam_vii.py` |

## Most contested

| Hero | Picks | Bans | Contest | Win % | Pick % | Ban % | Contest % |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Lone Druid | 8 | 90 | 98 | 62.5 | 7.8 | 88.2 | **96.1** |
| Clockwerk | 34 | 63 | 97 | 67.6 | 33.3 | 61.8 | **95.1** |
| Puck | 23 | 63 | 86 | 60.9 | 22.5 | 61.8 | 84.3 |
| Snapfire | 28 | 53 | 81 | 50.0 | 27.5 | 52.0 | 79.4 |
| Kez | 26 | 55 | 81 | 50.0 | 25.5 | 53.9 | 79.4 |
| Keeper of the Light | 29 | 50 | 79 | 58.6 | 28.4 | 49.0 | 77.5 |
| Doom | 20 | 51 | 71 | 65.0 | 19.6 | 50.0 | 69.6 |
| Shadow Fiend | 25 | 45 | 70 | 48.0 | 24.5 | 44.1 | 68.6 |
| Timbersaw | 19 | 49 | 68 | 31.6 | 18.6 | 48.0 | 66.7 |
| Bane | 32 | 34 | 66 | 62.5 | 31.4 | 33.3 | 64.7 |
| Axe | 29 | 36 | 65 | 58.6 | 28.4 | 35.3 | 63.7 |
| Hoodwink | 46 | 18 | 64 | 37.0 | 45.1 | 17.6 | 62.7 |
| Windranger | 36 | 28 | 64 | 36.1 | 35.3 | 27.5 | 62.7 |
| Tiny | 30 | 33 | 63 | 46.7 | 29.4 | 32.4 | 61.8 |
| Pangolier | 22 | 40 | 62 | 40.9 | 21.6 | 39.2 | 60.8 |

## Most picked

| Hero | Picks | Win % | Pick % |
| --- | ---: | ---: | ---: |
| Hoodwink | 46 | 37.0 | 45.1 |
| Lion | 42 | 45.2 | 41.2 |
| Windranger | 36 | 36.1 | 35.3 |
| Clockwerk | 34 | 67.6 | 33.3 |
| Bane | 32 | 62.5 | 31.4 |
| Treant Protector | 30 | 50.0 | 29.4 |
| Tiny | 30 | 46.7 | 29.4 |
| Axe | 29 | 58.6 | 28.4 |
| Keeper of the Light | 29 | 58.6 | 28.4 |
| Snapfire | 28 | 50.0 | 27.5 |

## Most banned

| Hero | Bans | Ban % |
| --- | ---: | ---: |
| Lone Druid | 90 | 88.2 |
| Clockwerk | 63 | 61.8 |
| Puck | 63 | 61.8 |
| Kez | 55 | 53.9 |
| Snapfire | 53 | 52.0 |
| Huskar | 53 | 52.0 |
| Doom | 51 | 50.0 |
| Keeper of the Light | 50 | 49.0 |
| Timbersaw | 49 | 48.0 |
| Shadow Fiend | 45 | 44.1 |

## Best and worst win rates (at least 5 picks)

| Best | Picks | Win % | | Worst | Picks | Win % |
| --- | ---: | ---: | --- | --- | ---: | ---: |
| Templar Assassin | 5 | 100.0 | | Tidehunter | 8 | 12.5 |
| Invoker | 9 | 88.9 | | Mars | 5 | 20.0 |
| Witch Doctor | 5 | 80.0 | | Enchantress | 9 | 22.2 |
| Enigma | 5 | 80.0 | | Tusk | 12 | 25.0 |
| Shadow Demon | 5 | 80.0 | | Timbersaw | 19 | 31.6 |
| Primal Beast | 5 | 80.0 | | Omniknight | 6 | 33.3 |
| Batrider | 9 | 77.8 | | Void Spirit | 6 | 33.3 |
| Ember Spirit | 20 | 70.0 | | Storm Spirit | 28 | 35.7 |
| Nature's Prophet | 10 | 70.0 | | Windranger | 36 | 36.1 |
| Clockwerk | 34 | 67.6 | | Dawnbreaker | 11 | 36.4 |

Five-pick samples are small: a 100% or 20% rate on 5 picks is one or two games from
ordinary. The high-volume signals are Clockwerk (34 picks, 67.6%) and Ember Spirit
(20 picks, 70.0%) winning, and Hoodwink (46 picks, 37.0%) and Windranger (36, 36.1%)
losing despite heavy play.
