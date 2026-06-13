# World Cup 2026 — Test Events This Weekend

*Investigation date: 2026-06-12 (Fri). Purpose: identify real, resolving matches we can use
as live test events for the Colony forecasting loop and the ClickHouse timestamp gate.*

The FIFA World Cup 2026 (USA / Canada / Mexico) group stage is underway — opened June 11,
2026. That means **real matches resolve this weekend**, which is exactly the live ground
truth Colony needs. Match outcomes are objective ground truth for the demo (plan §3, UMA
row). All times below are **Eastern Time**. English on Fox, Spanish on Telemundo.

> ⚠️ Note on the demo: §4 of the plan still holds — only a handful of matches have resolved
> tournament-wide, not nearly enough turnover to show generations live in 3 minutes. The
> **replay engine over resolved history remains the demo**. These live matches are best used
> to (a) test the x402 + timestamp gate against real resolving events, and (b) narrate the
> honest "starting now it runs live for 8 weeks" story.

## Fri, June 12 (today — may already be resolving)
| Time (ET) | Match | Group | Venue |
|---|---|---|---|
| 3:00 PM | Canada vs. Bosnia and Herzegovina | B | BMO Field, Toronto |
| 6:00 PM | USA vs. Paraguay | D | SoFi Stadium, Inglewood CA |

## Sat, June 13
| Time (ET) | Match | Venue |
|---|---|---|
| 3:00 PM | Qatar vs. Switzerland | — |
| 6:00 PM | Brazil vs. Morocco | — |
| 9:00 PM | Haiti vs. Scotland | — |

## Sun, June 14
| Time (ET) | Match | Venue |
|---|---|---|
| 12:00 AM | Australia vs. Turkey | — |
| 1:00 PM | Germany vs. Curaçao | — |
| 4:00 PM | Netherlands vs. Japan | — |
| 7:00 PM | Ivory Coast vs. Ecuador | — |
| 10:00 PM | Sweden vs. Tunisia | — |

(Venues left "—" where the search didn't surface them — fill from FIFA fixtures before relying on them.)

## Why these matter for our test plan
- **Real resolution to settle against.** Each match gives an objective outcome to test the
  `Match resolves → Settle bankroll` legs of the loop (flowchart) without an oracle dispute.
- **Timestamp-gate test fodder.** For each match at kickoff `T`, verify the ClickHouse gate
  returns only `ts <= T` data and refuses post-kickoff rows. Use a near-term match (e.g.
  Sat 6PM Brazil–Morocco) as the canonical leak test (see `../clickhouse/TODO.md` P0).
- **Beat-the-market check.** If we have Polymarket implied odds for any of these at the right
  timestamps, we can validate the beat-the-market bonus on a real event (plan §6 Q4).
  Favorites like Brazil and Germany are good cases to confirm "guessing the favorite" is NOT
  scored as skill (plan §7, Conceptual).

## Candidate canonical test match
**Brazil vs. Morocco, Sat June 13, 6:00 PM ET** — high public-odds liquidity (good chance of
Polymarket history), clear favorite (tests beat-the-market vs. guess-the-favorite), and a
convenient kickoff time for a live gate demo.

## Follow-ups
- [ ] Pull exact venues + UTC kickoff timestamps from FIFA fixtures for each match above.
- [ ] Check Polymarket for odds-history coverage on these specific fixtures (Q4 blocker).
- [ ] Pick the one match we wire end-to-end as the live x402 + gate test.

## Sources
- [2026 World Cup schedule — Yahoo Sports](https://sports.yahoo.com/soccer/article/2026-world-cup-schedule-teams-group-stage-match-dates-fixtures-how-to-watch-050724300.html)
- [2026 FIFA World Cup Schedule — CBS Sports](https://www.cbssports.com/soccer/news/world-cup-2026-schedule-times-dates/)
- [2026 FIFA World Cup Schedule — NBC Sports](https://www.nbcsports.com/soccer/news/2026-world-cup-schedule-kick-off-times-stadiums-dates-groups-how-to-watch-live-bracket)
- [2026 FIFA World Cup daily schedule (venues) — Yahoo Sports](https://sports.yahoo.com/soccer/article/2026-fifa-world-cup-daily-schedule-every-match-date-kickoff-time-and-venue-for-all-48-teams-234515087.html)
- [Matches — FIFA World Cup 2026 official](https://www.fifa.com/en/tournaments/mens/worldcup/canadamexicousa2026/scores-fixtures)
