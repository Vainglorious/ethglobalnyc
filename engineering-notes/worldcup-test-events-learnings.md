# World Cup 2026 — Live Test Events for the Demo (2026-06-12)

*Real, resolving matches we can use as live test events for the Colony forecasting loop and the
ClickHouse timestamp gate. Engineering record.*

## Why these matter
The FIFA World Cup 2026 (USA / Canada / Mexico) group stage opened June 11, 2026, so **real
matches resolve this weekend** — exactly the live ground truth Colony needs. Match outcomes are
objective ground truth for the demo (no oracle dispute needed). All times Eastern.

> ⚠️ The replay engine is still the demo. Only a handful of matches have resolved
> tournament-wide — nowhere near enough turnover to show generations live in 3 minutes. These
> live matches are best used to (a) test the x402 + timestamp gate against real resolving
> events, and (b) narrate the honest "starting now it runs live for 8 weeks" story.

## The matches that give a full lifecycle in the demo window
A complete cycle our agents could see end to end: buy data → stake → match resolves → settle
bankroll. Saturday, June 13, 2026:

| Time (ET) | Match | Group | Venue |
|---|---|---|---|
| 3:00 PM | Qatar vs. Switzerland | B | Levi's Stadium, Santa Clara CA |
| 6:00 PM | Brazil vs. Morocco | C | MetLife Stadium, East Rutherford NJ |
| 9:00 PM | Haiti vs. Scotland | C | Gillette Stadium, Foxborough MA |

These have a prediction market we can actually bet on **and** run a complete cycle (market open
→ bet → game played → resolved) inside our window — the candidates for the live x402 +
timestamp-gate test and the "agents see a full lifecycle" demo moment.

## Candidate canonical test match
**Brazil vs. Morocco, Sat June 13, 6:00 PM ET** — high public-odds liquidity (good chance of
Polymarket history), a clear favorite (tests *beat-the-market* vs. *guess-the-favorite*), and a
convenient kickoff for a live gate demo.

## How each match exercises the loop
- **Real resolution to settle against.** Each match gives an objective outcome to test the
  `Match resolves → Settle bankroll` legs without an oracle dispute.
- **Timestamp-gate test fodder.** For each match at kickoff `T`, verify the ClickHouse gate
  returns only `ts <= T` data and refuses post-kickoff rows (clickhouse/TODO.md P0).
- **Beat-the-market check.** If we have Polymarket implied odds at the right timestamps, we can
  validate the beat-the-market bonus on a real event. Favorites like Brazil are good cases to
  confirm "guessing the favorite" is **not** scored as skill.

## Follow-ups
- Pull exact venues + UTC kickoff timestamps from FIFA fixtures for every match.
- Check Polymarket for odds-history coverage on these specific fixtures (the Q4 blocker).
- Pick the one match we wire end-to-end as the live x402 + gate test.

## Sources
- 2026 World Cup schedule — Yahoo Sports / CBS Sports / NBC Sports
- Matches — FIFA World Cup 2026 official (fifa.com)
