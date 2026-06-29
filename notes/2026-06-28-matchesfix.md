# 2026-06-28 — World Cup matches fix (data refresh + FE)

Session notes for fixing the World Cup predictions page: the upcoming-matches list, the
"next match" logic, the trade ledger metadata, and the root-cause data-staleness bug.

## Root cause: the KG was never being refreshed
The whole World Cup data chain is:

```
OpenFootball 2026 (GitHub)  →  colony/colony_harness/tournament_graph.py
  https://raw.githubusercontent.com/openfootball/worldcup.json/master/2026/worldcup.json
        →  colony/data/world_cup_kg.json (committed snapshot, the KG)
        →  served by colony_api (/forecast/games, /kg/world-cup)
        →  copied into frontend/public/data/worldcup-games.json (FE static copy)
```

`build_kg.py` was run **once on June 13** and committed. It uses a local cache and only
re-fetches with `--force-refresh`, so it never updated. By June 28 OpenFootball had filled
in **73 results + the resolved Round-of-32 bracket**, but our frozen KG still had only **4
scores** (Jun 11–12) and unresolved bracket placeholders (`1C vs 2F`). The live colony_api
served the same stale file, so even "live" fetching wouldn't have helped — the source file
itself was stale.

Proof: live OpenFootball had `Brazil vs Japan` and `Germany vs Paraguay` (R32, 2026-06-29) —
exactly what Adil saw in the real bracket — while our KG had placeholders.

## The fix (data)
Reran the build forcing a fresh fetch:
```
PYTHONPATH=colony python3 colony/build_kg.py --force-refresh
```
- `colony/data/world_cup_kg.json` rebuilt: 104 match entities, **73 scored** (was 4),
  R32 resolved to real teams. 16 fixtures remain placeholders — the genuinely-undecided
  later rounds (R16 → Final), which is correct.
- Regenerated `frontend/public/data/worldcup-games.json` from the fresh KG (same shape:
  match_id/name/home_team/away_team/market_type/date/time/stage/group/venue/score/played),
  **including** played games with scores (104 games, 73 played).

> NOTE: colony_api still serves the stale KG until Railway redeploys (it reads its own
> deployed copy of `colony/data/world_cup_kg.json`). The FE uses the static copy, so the
> page is correct now regardless. Redeploy colony_api to refresh `/forecast/games`.

## The fix (frontend — frontend/public/worldcup/worldcup.js + worldcup.css)
1. **Live clock for "next match"** (replaces the old hardcoded `REF_DATE`):
   - `kickoffMs(g)` parses `date` + `"HH:MM UTC±N"` → absolute UTC instant (correct in any
     viewer timezone). `isPast/isUpcoming` compare to `Date.now()`. Upcoming list sorted by
     true kickoff, so "next" advances through the day automatically, per-viewer.
2. **Skip unresolved knockout placeholders** (Adil's choice when the clock ran past the
   group stage): `isResolvedFixture(g)` filters bracket tokens (`1C`, `3A/B/C/D/F`, `W73`)
   out of next-match + upcoming. When no real matchup remains, a graceful
   `bracketPendingCard()` shows "Group stage complete — knockout bracket resolving" instead
   of garbage. With fresh data this no longer triggers (next = Brazil vs Japan), but stays
   as the safety net for future undecided rounds.
3. **Copy:** "Upcoming fixtures" → "Upcoming matches"; "How the Edge Works" → "Looking for
   Edges".
4. **Settled vs Open badge** on any fixture the colony has a position on (from `isPast`).

## The fix (trade ledger — predictions.json + worldcup.js)
- Synced root `predictions.json` (12 trades) into the FE copy (it was stuck at 11 — missing
  the manual #12 placed 6/21).
- **Backfilled metadata for the 4 bare-market trades (#9–#12).** They only carried a
  `polygun_market_id` + `outcome_token_id` because PolyGun returns only machine ids at fill
  time. Resolved them by matching `outcome_token_id` against the **ClickHouse markets
  catalog** (`/markets/search` on the deployed clickhouse_api), which maps token_id →
  question/outcome:
  - #9  `1897108` → Czech Republic vs. South Africa (6/18), "South Africa win" → lost
  - #10 `1897246` → Panama vs. Croatia (6/23), "Panama win" → (was the open bet)
  - #11 `1897121` → Scotland vs. Morocco (6/19), "Scotland win" → lost
  - #12 `1897171` → Belgium vs. Iran (6/21), "draw" → **won**
  Wrote event/market_question/outcome + a resolution note into each trade.
- **Filled `MARKET_OVERRIDES`** in worldcup.js with the 4 confirmed mappings (also supplies
  date + home/away for the draw market, whose question has no date).
- **Generalized draw handling** in `buildIndex`/`betsFor` so the Belgium–Iran draw pins to
  its fixture via the override's teams+date (old Qatar/Switzerland sim read still works).
- **Reordered the On-chain Ledger** table to **latest bets first** (sort by ts_utc desc).
  The "unmapped trades" footnote disappears now that every trade has an `event`.

## "Colony's match picks" = 8 cards (explained)
The section shows every fixture with ≥1 colony bet (one card per match), matched by
date + team from predictions.json (real) + simulatedtransactions.json (sim). 12 trades
collapse to 8 cards: −2 France outright futures (shown in the Outright/Futures panel),
−1 Scotland double-fill (#5/#6 same match), −1 Turkey #7 unmatched (see below) = 8.

## Known minor issue (not fixed — left for Adil's call)
- **Turkey bet #7 doesn't attach to its fixture.** Bet is dated `2026-06-14`
  ("Will Turkiye win on 2026-06-14?") but the KG fixture *Australia vs Turkey* is dated
  `2026-06-13` (Polymarket UTC date vs OpenFootball local kickoff date). Date mismatch →
  the pick silently drops, so it's the missing 9th "Colony match pick". Fix would be a
  date-normalization or a MARKET_OVERRIDES-style pin. Adil aware.

## Verified
- Dev server (Vite) on **localhost:3000** serves the app with fresh data (104 games, 73
  scored) and all JS fixes present.
- Next match renders as **Brazil vs Japan**, then the real R32 rail.
- Colony picks now show win/loss chips (group results populated). Note: most group picks
  lost — that's just the true data surfacing (Adil: don't worry about the losses).

## Follow-ups (open)
- **Automate the refresh** so this never goes stale: cron/GitHub Action running
  `build_kg.py --force-refresh` → re-commit KG → redeploy colony_api. Ties into the
  `/worldcup/feed` handover (notes/handover/colony-api-worldcup-feed.md) — that endpoint
  could serve a live `as_of` + the merged feed so the FE drops its static snapshots.
- Optionally fix the Turkey #7 date mismatch.
