# ClickHouse Rail — the metered knowledge plane

The **knowledge plane** of Colony. A ~1 TB prediction-market + match-results corpus
that ants must **pay USDC to query**, gated by a real HTTP 402 handshake (x402).
Making thinking cost money is what gives an ant's decisions weight.

This folder is scaffolding only — interface + TODOs, no committed language yet.
See `../colony/README.md` for the core loop and `../notes/colony-hackathon-plan (1).md` §3–§4.

## What this rail owns

1. **The corpus.** Timestamped prediction-market odds (Polymarket history) + resolved
   match outcomes. The moat. Fitness is "beat the market," which is only real if odds
   history exists at the right timestamps (plan §6, Q4).
2. **The x402 gate.** A `402 → pay → 200 → query` HTTP endpoint. An ant hits the query
   API, gets a 402 with a price, settles USDC on Arc, retries with proof, gets data.
   This is the canonical x402 pattern — nothing faked (plan §3, Arc row).
3. **The timestamp gate (THE CARDINAL RULE).** At simulated time `T`, a query may only
   return rows with `ts <= T`. One leak of future data and every result is a lie
   (plan §4 / §7). **Build and test this gate before anything else.**

## Interface contract (strawman — confirm with rail owner A)

```text
POST /query
  body:  { sql | structured query, as_of_ts: T, ant_id, lineage_tier }
  → 402  { price_usdc, pay_to (Arc addr), nonce }      # if unpaid
  → 200  { rows, priced_at, as_of_ts }                 # rows all satisfy ts <= as_of_ts
```

- `as_of_ts` is enforced server-side; the ant cannot widen its own window.
- `lineage_tier` (from the Worldcoin rail) may unlock a **premium data tier** for
  verified lineages — see `../worldcoin/README.md`.
- Price is a function of query cost so data meaningfully trades against bankroll
  (plan §6, Q6: too cheap → no decision pressure; too expensive → starvation).

## How ants consume it

The harness already models a `query_budget` gene and `source_weights` over
ClickHouse stats / Polymarket odds / social signal (`../colony/colony_harness/genes.py`).
This rail is the real backend behind that budget: a debit per query, returning the
priced data the parametric decision function consumes.

## Build order (do NOT reorder the first two)

- [ ] **Timestamp gate + a test that fails on any `ts > T` leak.** First. Always.
- [ ] **"Hello, 402" spike:** `402 → pay on Arc testnet → 200`, end to end, day one.
      (plan §7: discovering broken x402/faucet at hour 30 ends the project.)
- [ ] Load corpus: confirm we actually have odds history AND outcomes at aligned ts.
- [ ] Query API + pricing function.
- [ ] Premium-tier hook for verified lineages.
- [ ] Wire `query_budget` debits into the colony settlement on Arc.

## Open questions (blocking)

- Do we have Polymarket implied-odds history at the right timestamps? (plan §6 Q4)
- Exact pricing so data cost trades meaningfully against bankroll? (plan §6 Q6)
- ClickHouse hosting: local replica for the demo vs. remote 1 TB instance + RPC limits?

## TODO stubs to add next

```text
clickhouse/
  README.md            # this file
  schema/              # table DDL: odds_history, match_results, ...
  gate/                # timestamp-gate logic + the leak test (FIRST)
  x402/                # 402 handshake middleware + Arc settlement glue
  api/                 # /query endpoint + pricing function
  seed/                # corpus load / fixtures for the replay engine
```
