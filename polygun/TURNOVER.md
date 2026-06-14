# PolyGun Execution Layer — Dev Turnover

Handoff so the rest of the team can wire the **colony consensus → real Polymarket
trade** loop. The execution side is built and proven; the colony just needs to
emit a **pick**. This doc + the `polygun/` code is everything you need.

> Why this exists: Polymarket's direct CLOB API **geoblocks the US** (signed order
> → `403`). **PolyGun** is a Telegram bot that trades **custodially via its own
> relayer**, sidestepping the geoblock. It has **no API**, so we drive it with a
> Telethon **userbot** (`pg.py`). Deposited USDC → **pUSD**; trades return real
> Polymarket outcome tokens.

---

## TL;DR for colony devs

There is **ONE shared PolyGun execution account** — the funded Telegram account.
**That is the final execution layer. Do NOT create or integrate a new account.**
You drive THIS account directly with `pg.py`.

The colony's job each match: output a consensus **pick** — which **outcome** + how
much **USD** — which maps 1:1 to one command:

```
polygun/.venv/bin/python polygun/pg.py buy --market <MARKET_ID> --side yes --amount <USD> --confirm
```

Each outcome is its own Yes/No market — to bet an outcome you **Buy Yes** on *its*
market id. The colony picks the outcome + stake; resolve it to the market id (below).

To run it you need two gitignored runtime files that **Adil shares securely
(NOT via git):** `polygun/.env` and `polygun/pg.session`. With those + the venv,
the command above trades the shared funded account. Setup is below.

### Handoff format (what the colony should emit)
```json
{ "event": "Brazil vs. Morocco (Jun 13)", "outcome": "Brazil",
  "polygun_market_id": 1897049, "side": "yes", "amount_usd": 2,
  "colony_prob": 0.63, "market_price": 0.59 }
```
Minimum viable: just `"Brazil, $2"` and the operator resolves the market id.

---

## Getting market ids (how we resolve a pick → id)

PolyGun search is the source of truth (winner markets only — O/U/props are NOT on
PolyGun; see Limitations). Flow:

```
pg.py send "/start"                         # menu
pg.py click <menu_msg_id> 0 0               # Markets
pg.py send "Brazil Morocco"                 # search -> results w/ Trade deep-links
pg.py send "/start ref_<refcode>__e_<EVENT>"   # open the match event
pg.py send "/start ref_<refcode>__m_<MARKET>"  # open one outcome -> Buy panel
```
Deep links are sent as `/start <param>`. `<refcode>` = the Telegram username
lowercased (in `PG_REFCODE`). Example resolved ids (2026-06-13):

| Match | Event | Outcomes (market id) |
|---|---|---|
| Qatar vs Switzerland | e_351719 | SUI 1897048 · Draw 1897047 · QAT 1897046 |
| Brazil vs Morocco | e_351720 | BRA 1897049 · Draw 1897050 · MAR 1897051 |
| Haiti vs Scotland | e_351721 | SCO 1897054 · Draw 1897053 · HAI 1897052 |

> Heads-up: PolyGun **MARKET buys have no confirm step** — sending the amount
> fires the trade. `pg.py buy` (no `--confirm`) stops *before* sending the amount.

---

## Setup — operate the shared execution account

The code is in git; the runtime bits are **gitignored** and come from **Adil
OUT-OF-BAND** (secure channel — Signal / 1Password / encrypted DM; never git or
plaintext Slack). Two files:

  1. `polygun/.env`       — Telegram api creds + PolyGun config for the shared account
  2. `polygun/pg.session` — the already-logged-in Telethon session for that account
     (this is what lets you drive the funded account WITHOUT a fresh login code)

Steps:
```bash
python3 -m venv polygun/.venv
polygun/.venv/bin/pip install -r polygun/requirements.txt   # just Telethon
# drop the .env and pg.session Adil sent you into polygun/
polygun/.venv/bin/python polygun/pg.py whoami               # should print the shared account
polygun/.venv/bin/python polygun/pg.py buy --market <id> --side yes --amount 2 --confirm
```

What `polygun/.env` contains (Adil sends the real values):
```
TG_API_ID=...           # Telegram app id for the shared account (my.telegram.org)
TG_API_HASH=...         # Telegram app hash (SECRET)
TG_PHONE=...            # account phone — only needed for a fresh login
PG_REFCODE=...          # referral handle in deep links (the account username, lowercased)
PG_BOT=PolyGunSniperBot
```
(If `pg.session` ever expires, `pg.py login` re-auths — but the code goes to the
account owner's Telegram, so coordinate with Adil.)

### CRITICAL — single driver at a time
`pg.session` is the SAME account for everyone who has it. Telegram can flag an
account that's active from multiple IPs/devices simultaneously, and overlapping
trades cause double-bets. So:
- Only **one person/machine** drives the account at a time (the owner's phone app
  counts too). Coordinate before you run `buy`.
- PolyGun's confirmation **can lag** — a "Transaction Submitted" with no
  confirmation may STILL have filled. **Verify on-chain before re-running**, or you
  double-bet (we did exactly this on Scotland: ~$4 instead of $2).

---

## Ledger + recording

- **`predictions.json`** (repo root) — every REAL trade as hard on-chain data
  (ts, shares, token id, pUSD spent/fee, avg price, tx, block). Source of truth.
- **`polygun/record_trade.py <tx> --market <id> ...`** — idempotent recorder;
  decodes the tx on-chain and appends. Run it after each fill. (Needs `certifi`;
  run it with a venv that has it, e.g. the `polymarket/.venv`.)
- **`simulatedtransactions.json`** — clearly-labeled HYPOTHETICAL bets (counterfactual
  study). Never mixed with real trades.

Trades so far: France-to-win ×2 (manual + auto), Switzerland-to-win, Brazil-to-win,
Scotland-to-win (the live demo run). ~$2 each.

---

## Limitations / lessons (carry into the colony)

1. **Winner markets only on PolyGun.** O/U totals, corners, exact scores exist on
   Polymarket and are discoverable via **ClickHouse** (`default_v3.polymarket_markets_all`)
   but are NOT tradeable from here (PolyGun doesn't index them; CLOB geoblocks US).
2. **Speed is the bottleneck, not the trade path.** A live in-game arb (the 1-1
   draw) repriced before we could act — needs a live-score feed faster than the
   market. (See `simulatedtransactions.json`.)
3. **Price off the live source** (PolyGun), not ClickHouse's batch table (it lags
   minutes).
4. **Neg-risk (multi-outcome) markets** (match winners) have split/merge token
   flows — sanity-check `avg_price` vs PolyGun's "Average Price" when recording.
5. **Check the outcome market before betting** — a quote near 100¢/0 = resolved/
   closing book; don't market-buy into it.

## Repo pointers
- `polygun/pg.py` — userbot controller (login/whoami/dump/snapshot/send/click/buy)
- `polygun/record_trade.py` — on-chain trade recorder
- `clickhouse/DATA_CATALOG.md` — market/odds/UMA data we can query
- `notes/2026-06-13-3pm-bets-dev-handoff.md` — the 3-bet plan + data sources
- `notes/2026-06-13-polygun.txt` — custody model, decoded trades, automation history
