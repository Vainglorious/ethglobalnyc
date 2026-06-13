# Polymarket Integration

Hook the Colony into Polymarket: read **implied odds** (the "beat-the-market"
benchmark from the planning doc) and **execute orders** (the economic plane —
proving an ant can actually trade).

> **Polymarket is mainnet-only.** It runs on **Polygon (chain 137)** with
> **USDC.e** as collateral. There is no testnet, so a "test trade" is a tiny
> **real** order. Every guard in here exists because of that.

## Layout

| File | What it does | Needs a key? |
|---|---|---|
| `connectivity_check.py` | Read-only smoke test of the public CLOB + Gamma APIs; prints a live tradable `token_id` + prices | No |
| `config.py` | Loads `.env` (+ `.env.test` overrides); auto-points TLS at certifi | — |
| `pm_client.py` | Builds an authenticated `ClobClient` (wallet + L2 API creds) | Yes |
| `check_account.py` | Address, derived API creds, USDC balance/allowance; `--approve` sets allowance | Yes |
| `place_test_trade.py` | Builds + (only on demand) posts ONE tiny order; dry-run by default | Yes |
| `execute_colony_bets.py` | Converts Colony debate forecasts into a capped 2-3 agent trade plan, then optionally posts orders | Yes for posting |
| `.env` / `.env.test` | Your real secrets / test-order knobs (both gitignored) | — |

## Quick start

```bash
# 1. (no key needed) confirm we can reach Polymarket and grab a live token_id
python polymarket/connectivity_check.py

# 2. install deps for the authenticated parts
python -m venv polymarket/.venv && source polymarket/.venv/bin/activate
pip install -r polymarket/requirements.txt

# 3. fill in polymarket/.env  -> POLYMARKET_PRIVATE_KEY (a funded Polygon wallet)
#    then inspect the account + grab/derive API creds
python polymarket/check_account.py

# 4. one-time: approve the Exchange to spend your USDC.e (costs a little gas)
python polymarket/check_account.py --approve

# 5. configure the order in polymarket/.env.test (paste PM_TEST_TOKEN_ID from step 1),
#    dry-run it first (safe), then execute for real
python polymarket/place_test_trade.py                       # dry run
#   ...set PM_DRY_RUN=false in .env.test...
python polymarket/place_test_trade.py --execute             # real, tiny order
```

## Debate-driven bets

After a Colony debate run, use the generated `forecasts.csv` as the input for a
small Polymarket trade plan. For the first live test, keep the data loop simple:
let the agents debate with the datasources we already have, then refresh the
market prices roughly 10 minutes before the game and buy whichever side has the
better live edge for the strongest few agents.

```bash
python polymarket/execute_colony_bets.py \
  --run-dir colony/runs/<run_id> \
  --home-token-id <HOME_CLOB_TOKEN_ID> \
  --away-token-id <AWAY_CLOB_TOKEN_ID> \
  --max-agents 3
```

If you already copied the 10-minute prices from the order book, pass them
explicitly to avoid a live price fetch:

```bash
python polymarket/execute_colony_bets.py \
  --run-dir colony/runs/<run_id> \
  --home-token-id <HOME_CLOB_TOKEN_ID> \
  --away-token-id <AWAY_CLOB_TOKEN_ID> \
  --home-ask 0.61 \
  --away-ask 0.42 \
  --max-agents 3 \
  --max-total-usdc 2
```

By default this only prints the plan. To post real orders, the same double guard
is required:

```bash
# set PM_DRY_RUN=false in polymarket/.env.test first
python polymarket/execute_colony_bets.py ... --execute
```

Useful knobs:

- `--max-agents 2` or `--max-agents 3`: only a few ants make the first real bet.
- `--max-total-usdc`: hard cap across all selected ants.
- `--max-per-agent-usdc`: per-ant cap.
- `--lock-forecast-side`: keep each ant on its original home/away decision instead
  of reselecting the better side from the latest ask prices.
- `--include-passes`: allow agents that passed during the debate to become
  eligible if the late price creates a fresh edge.

## Wallet setup (the part you own)

For an API bot the simplest path is a **plain EOA** (`POLYMARKET_SIGNATURE_TYPE=0`):

1. Create a fresh wallet, put its `0x` private key in `.env` (`POLYMARKET_PRIVATE_KEY`).
2. Fund it on **Polygon** with a small amount of **USDC.e**
   (`0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174`) plus a little **MATIC/POL** for gas.
3. Run `check_account.py --approve` once to set the USDC allowance.

If instead you're using a Polymarket UI account (email/magic or browser wallet),
funds live in a **proxy wallet** — set `POLYMARKET_SIGNATURE_TYPE=1` (magic) or `2`
(browser/Safe) and `POLYMARKET_FUNDER_ADDRESS` to that proxy address, signing with
the associated EOA key.

## Safety guards on `place_test_trade.py`

An order posts **only** when **all** of these hold:
1. `PM_DRY_RUN=false` in `.env.test`, **and**
2. `--execute` passed on the CLI, **and**
3. notional (`price × size`) ≤ `PM_MAX_TEST_USDC`.

Default state is fully safe: dry-run prints the order without posting.

## How this connects to Colony

- **Data:** Polymarket implied odds feed the `odds`/market signals and the
  *beat-the-market* fitness bonus — an ant is only "skilled" if it beats these.
- **Execution:** `place_test_trade.py` proves the order path end-to-end. Later,
  an ant's `Forecast` (`side` + `stake`) maps onto `OrderArgs` so the colony's
  sealed bets can settle as real CLOB orders.
- **Debate to trade:** `execute_colony_bets.py` is that first bridge: it reads
  `forecasts.csv`, recomputes live edge from the current home/away asks, selects
  at most a few capped agents, and only posts when the dry-run guard is disabled
  and `--execute` is passed.

## Notes

- `connectivity_check.py` is pure stdlib — no install needed.
- On macOS python.org Python, TLS can fail with `CERTIFICATE_VERIFY_FAILED`;
  `config.py` auto-sets `SSL_CERT_FILE` from `certifi` when it's installed.
- `.env` and `.env.test` are gitignored. Never commit a private key.
