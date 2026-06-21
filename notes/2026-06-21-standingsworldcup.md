# 2026-06-21 — World Cup standings & reconciling the FE "positions"

## TL;DR (read this first)

1. **We cannot show real "current standings."** The only results that exist in the
   project are **4 matches from June 11–12** in `colony/data/world_cup_kg.json`
   (mirrored to `frontend/public/data/worldcup-games.json`). Every fixture from
   **June 13 onward — including every game the FE shows a pick on — has `score: null`.**
   I also have no independent knowledge of real 2026 results (model cutoff predates the
   tournament). So any "standings" past June 12 would be invented. Don't ship invented ones.

2. **The FE is not showing open positions — it's showing settled history.** The
   Switzerland / Brazil / Scotland / Ecuador "Colony picks" are **real, already-filled
   trades from June 13–15** (`predictions.json`, all `status: filled`). Those matches are
   in the past relative to today (2026-06-21), so those positions are **closed**, not
   outstanding. The FE renders them as match-pick badges, which reads like live exposure.

3. **You're right about the one forward-looking match bet: Panama.** The only un-played
   match the colony has a position on is **Panama vs Croatia, 2026-06-23 (Group L)**.
   The opponent *is* set — it's **Croatia**. (Plus the two **France "to win the World Cup"
   futures**, which stay open until the final on July 19.)

---

## What "standings" we can actually back with data

Tournament: 48 teams, 12 groups (A–L), 104 group/knockout fixtures, June 11 – July 19 2026.
Played matches with committed scores in our KG: **4** (only Groups A, B, D have any result).

### Group A — 2 of 6 played
| # | Team | P | W | D | L | GD | Pts |
|---|------|---|---|---|---|----|-----|
| 1 | Mexico | 1 | 1 | 0 | 0 | +2 | 3 |
| 2 | South Korea | 1 | 1 | 0 | 0 | +1 | 3 |
| 3 | Czech Republic | 1 | 0 | 0 | 1 | −1 | 0 |
| 4 | South Africa | 1 | 0 | 0 | 1 | −2 | 0 |

Results: Mexico 2–0 South Africa · South Korea 2–1 Czech Republic.

### Group B — 1 of 6 played
| # | Team | P | W | D | L | GD | Pts |
|---|------|---|---|---|---|----|-----|
| 1 | Canada | 1 | 0 | 1 | 0 | 0 | 1 |
| 1 | Bosnia & Herzegovina | 1 | 0 | 1 | 0 | 0 | 1 |
| 3 | Qatar | 0 | — | — | — | 0 | 0 |
| 3 | Switzerland | 0 | — | — | — | 0 | 0 |

Result: Canada 1–1 Bosnia & Herzegovina. **Qatar v Switzerland (the colony's "Switzerland
@ 85¢" bet) has no committed score** — we don't actually know that result from repo data.

### Group D — 1 of 6 played
| # | Team | P | W | D | L | GD | Pts |
|---|------|---|---|---|---|----|-----|
| 1 | USA | 1 | 1 | 0 | 0 | +3 | 3 |
| 2 | Australia | 0 | — | — | — | 0 | 0 |
| 2 | Turkey | 0 | — | — | — | 0 | 0 |
| 4 | Paraguay | 1 | 0 | 0 | 1 | −3 | 0 |

Result: USA 4–1 Paraguay.

### All other groups (C, E, F, G, H, I, J, K, L) — 0 played
No results committed. Standings are all 0–0–0. This includes **Group C** (Brazil, Morocco,
Haiti, Scotland — the Brazil & Scotland bets) and **Group E** (Ivory Coast, Ecuador — the
Ecuador bet). The colony bet these games but the KG never got their scores.

> **Data-quality flag:** the KG was built from an OpenFootball 2026 snapshot that only had
> the first 4 results filled in. To show honest standings we either (a) refresh
> `world_cup_kg.json` from a live results source, or (b) clearly label the page "schedule +
> early results only — standings TBD." Right now option (b) is the truthful one.

---

## Reconciling the FE "Colony's match picks" panel

What the panel currently shows vs. reality:

| FE shows | Source | Real status |
|---|---|---|
| Switzerland @ 85¢ (Qatar v Switzerland, 6/13) | `predictions.json` trade | **Closed** — filled 6/13, match in the past |
| Brazil @ 59¢ (Brazil v Morocco, 6/13) | `predictions.json` trade | **Closed** — filled 6/13 |
| Scotland @ 55¢ (Haiti v Scotland, 6/13) | `predictions.json` (2 fills — the accidental double) | **Closed** — filled 6/14 |
| Ecuador @ 32¢ (Ivory Coast v Ecuador, 6/14) | `predictions.json` trade | **Closed** — filled 6/15 |
| *(also in ledger, not on a fixture row)* Turkiye (Australia v Turkey, 6/14) | `predictions.json` | **Closed** |

These are **historical, settled picks**, so showing them as match-pick badges overstates
current exposure. Suggested FE fix: split "Colony's match picks" into **Settled (history)**
vs **Open (forward-looking)**, gated on fixture date vs. today — or move past picks into the
On-chain Ledger only and let the schedule grid show open positions exclusively.

### What is genuinely *outstanding* (un-settled) right now
- **Panama vs Croatia — 2026-06-23, Group L** (opponent confirmed: Croatia). This is the one
  forward-looking match bet. It's one of the three bare-market trades (#1897108 / #1897246 /
  #1897121, placed 6/18–6/19) — `MARKET_OVERRIDES` still needs the confirmed Panama id.
- **France to win the World Cup** — 2 outright futures (#1 manual, #2 auto), open until the
  final (July 19). Not tied to a fixture; the outright panel already handles these.

### Panama's group context (Group L)
Teams: Croatia, England, Ghana, Panama. Fixtures:
- 6/17 Ghana v Panama · England v Croatia *(no scores in KG)*
- **6/23 Panama v Croatia** ← our open bet · England v Ghana
- 6/27 Panama v England · Croatia v Ghana

We have no committed results for Group L, so Panama's table position is unknown from repo
data — treat the 6/23 market on its own merits, not on a standings read we don't have.

---

## Action items
- [ ] Decide FE framing: label World Cup data "schedule + early results only" until the KG
      has more scores, OR refresh `world_cup_kg.json` from a live results feed.
- [ ] Split FE match picks into **Settled** vs **Open** so closed trades stop reading as
      live exposure.
- [ ] Confirm which bare market id (`1897108` / `1897246` / `1897121`) is the Panama 6/23
      bet from the Polymarket profile, then fill `MARKET_OVERRIDES`.
- [ ] Identify the other two bare-market trades (or leave them in the "Unmapped" footnote).
