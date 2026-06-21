# Direct CLOB betting — setup (Belgium vs. IR Iran, and any game)

Self-custody path: sign + post Polymarket CLOB orders ourselves from the treasury
`0xcc16…` (USDC.e on Polygon). Parallel to the PolyGun path. Script:
`polymarket/bet_bel_irn_clob.py`.

## Status (2026-06-21)
- ✅ **Geoblock cleared** from our Toronto/Canada egress (no 403 — the order reaches
  the matching engine). Keep the tunnel ON; tunnel OFF → East Africa = untested.
- ✅ Funds ready: treasury holds ~6 USDC.e + POL gas.
- ✅ Order **builds + signs** correctly (neg-risk handled — the thing
  `place_test_trade.py` was missing). Verified via dry-run.
- ⛔ **The POST is blocked** on the published client: `py-clob-client 0.34.6`
  (latest on PyPI) emits an order the server rejects with
  `"invalid order version, please use the latest clob-client"`. The contracts in
  0.34.6 are current, so it's the order *schema* that lags — fixed in the GitHub head.

## The 3 one-time prerequisites (you run these — I'm gated from the git install)
1. **Egress:** Toronto/Canada tunnel ON.
2. **Upgrade the client** (fixes "invalid order version"):
   ```bash
   ! polymarket/.venv/bin/python3 -m pip install -U "git+https://github.com/Polymarket/py-clob-client.git"
   ```
3. **USDC.e allowance to the SIGNING exchanges** (the earlier `approve_usdce.py`
   approved the *old* spenders; CLOB fills settle through `0x4bFb…`/`0xC5d5…`):
   ```bash
   ! polymarket/.venv/bin/python3 polymarket/approve_usdce_clob.py
   ```

## Then bet (same shape as the PolyGun script)
```bash
# live book, all three sides (no bet):
polymarket/.venv/bin/python3 polymarket/bet_bel_irn_clob.py --show
# dry run (build + sign, NO post — no money):
polymarket/.venv/bin/python3 polymarket/bet_bel_irn_clob.py belgium
# FIRE ($2) — self-custody fill on Polygon:
polymarket/.venv/bin/python3 polymarket/bet_bel_irn_clob.py belgium --go
```
On a real fill, grab the on-chain tx and record it:
```bash
! python polygun/record_trade.py <txhash> --market <id> --execution-layer polymarket-clob
```

## CLOB vs PolyGun (when to use which)
| | PolyGun (`polygun/bet_bel_irn.py`) | Direct CLOB (`bet_bel_irn_clob.py`) |
|---|---|---|
| Custody | custodial (pUSD pooled) | **self** (our keys/USDC.e) |
| Works today | ✅ proven (5 trades) | ⛔ until client upgrade (prereq #2) |
| Speed | human-paced (Telegram) | sub-second; real automation/HFT |
| Geo | relayer (any region) | needs allowed-region egress (Toronto ✅) |

Once prereq #2 is done, CLOB is the better rail for fast/last-minute fills (no
Telegram lag, true self-custody). Until then, PolyGun is the working fallback.
