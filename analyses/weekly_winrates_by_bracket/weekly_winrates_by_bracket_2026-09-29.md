# Top win-rate heroes by rank, week of 2026-09-10 (run 2026-09-29)

A dated snapshot of one run of
[`weekly_winrates_by_bracket.py`](weekly_winrates_by_bracket.py), not maintained policy.
Request and scope are in
[`weekly_winrates_by_bracket.context.json`](weekly_winrates_by_bracket.context.json).
The original prompt is lost; the analysis implemented step 3 of the v1 design ("run one
end-to-end analysis ... to validate the loop").

Question: for each rank, which heroes had the highest win rate in the latest complete
week, and does the data pass the 50% sanity check?

| | |
| --- | --- |
| Data | Stratz `heroStats.winWeek`, ranked All Pick, last 8 weeks per rank; fetched live on 2026-09-29 |
| Period | Week starting Thursday 2026-09-10, the latest complete week Stratz had |
| Scope | Every position pooled; one table per rank, Herald to Immortal |
| Measure | Win rate = wins / picks (`matchCount` counts picks, 10 per match); cells under 200 picks suppressed |
| Rerun | `uv run analyses/weekly_winrates_by_bracket/weekly_winrates_by_bracket.py` (a later rerun fetches newer weeks) |

**Data lag.** On 2026-09-29, Stratz's hero statistics stopped at 2026-09-17, in both the
weekly and daily buckets, so the "latest complete week" is about two weeks old. Daily
volumes also fell about fivefold from 2026-09-03 (measured for position 1 in the same
session).

## Sanity: pick-weighted mean win rate per rank (8 weeks)

| Rank | Picks | Mean win rate |
| --- | ---: | ---: |
| Herald | 7,268,380 | 0.5 |
| Guardian | 27,568,250 | 0.5 |
| Crusader | 43,650,380 | 0.5 |
| Archon | 55,674,330 | 0.5 |
| Legend | 55,288,620 | 0.5 |
| Ancient | 38,081,070 | 0.5 |
| Divine | 19,982,340 | 0.5 |
| Immortal | 11,594,180 | 0.5 |

Every rank passes.

## Top 5 by win rate, week of 2026-09-10

| Rank | 1 | 2 | 3 | 4 | 5 |
| --- | --- | --- | --- | --- | --- |
| Herald | Spectre 56.9% (4,627) | Wraith King 55.3% (5,108) | Crystal Maiden 54.9% (7,418) | Chaos Knight 54.2% (3,074) | Phantom Lancer 54.1% (5,434) |
| Guardian | Wraith King 55.5% (24,346) | Spectre 55.1% (24,203) | Meepo 53.7% (3,975) | Arc Warden 53.5% (8,668) | Crystal Maiden 53.4% (31,377) |
| Crusader | Wraith King 55.8% (45,408) | Spectre 54.0% (45,402) | Lich 53.6% (33,051) | Vengeful Spirit 53.2% (36,600) | Legion Commander 53.0% (53,543) |
| Archon | Wraith King 54.7% (66,684) | Meepo 53.8% (7,441) | Spectre 53.7% (64,401) | Visage 53.6% (6,621) | Lifestealer 53.2% (96,634) |
| Legend | Visage 54.9% (7,729) | Meepo 54.3% (7,524) | Wraith King 54.3% (71,757) | Bounty Hunter 54.2% (50,205) | Outworld Destroyer 53.8% (50,246) |
| Ancient | Bounty Hunter 55.6% (42,743) | Visage 54.9% (6,284) | Wraith King 54.0% (45,989) | Outworld Destroyer 54.0% (39,982) | Meepo 53.6% (5,434) |
| Divine | Meepo 56.5% (2,692) | Visage 56.4% (3,528) | Enigma 56.4% (9,493) | Bounty Hunter 56.4% (26,189) | Elder Titan 54.7% (2,299) |
| Immortal | Bounty Hunter 56.9% (19,814) | Enigma 56.8% (7,491) | Visage 56.1% (2,719) | Meepo 55.5% (1,542) | Elder Titan 54.6% (1,619) |

Picks in brackets. The pattern: Wraith King and Spectre dominate the lower and middle
ranks, while Bounty Hunter, Enigma and the specialists (Visage, Meepo, Elder Titan)
lead from Legend up. The specialists' samples are small and self-selected.
