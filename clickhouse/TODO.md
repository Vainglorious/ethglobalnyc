# ClickHouse Rail — TODO

Owner: dev A (Arc chain, wallets, x402, ClickHouse gate — plan §5).

## P0 — must work before anything else
- [ ] Timestamp gate: server-side enforce `ts <= as_of_ts` on every query.
- [ ] Leak test: a test that FAILS if any returned row has `ts > as_of_ts`.
- [ ] "Hello 402" spike: `402 → pay (Arc testnet USDC) → 200` round-trip, day one.

## Access layers
- [x] Layer 1 "uma-clickhouse-oracle": user `adil_hackathon_claude` — free range on
      `umalabs.*` (read/write/DDL) + read-only on the two `default_v3.polymarket_markets_*`
      tables. See ../notes/2026-06-12-clickhouse-uma.txt.
- [ ] Layer 2: grant access to the OTHER data (broader `default_v3`, odds-history, etc.),
      explicitly table by table, once we know what `/query` reads.

## P1 — corpus + API
- [ ] Confirm corpus has Polymarket odds history AND match outcomes at aligned timestamps.
- [ ] Table DDL: `odds_history`, `match_results` (+ keys on event_id, ts).
- [ ] `/query` endpoint returning `{rows, as_of_ts}`.
- [ ] Pricing function (query cost → USDC), tuned vs. bankroll (plan §6 Q6).

## P2 — integration
- [ ] Premium data tier unlocked by verified `lineage_tier` (worldcoin rail).
- [ ] Wire `query_budget` debits into Arc settlement / colony bankroll.
- [ ] Seed/fixtures feeding the replay engine (plan §4).

## Notes
- Cardinal rule: lookahead leakage makes the whole project a lie. Gate first, test first.
- See ../notes/worldcup-test-events-2026-06-12.md for real matches to test the gate against.
