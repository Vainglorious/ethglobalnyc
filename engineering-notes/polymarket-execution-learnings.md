# Polymarket Execution — Direct CLOB, PolyGun & Live Betting (2026-06-13)

*How Colony actually places real bets on Polymarket — the geoblock that killed the direct
path, the custodial workaround that worked, and the live in-play betting plan. Engineering
record.*

## The headline finding: direct CLOB is geoblocked in the US
We took the direct `py-clob-client` path all the way to a live order — our code built, signed
(EIP-712), and **POSTed** a real $2 "France to win the World Cup" order. Polymarket rejected it:

> **HTTP 403 — "Trading restricted in your region."**

Polymarket's CLOB **geoblocks the US**. We're in NYC, so direct-API trading is a dead end here
regardless of funds/allowances — a hard wall at their API, not a bug in our setup. Our stack is
otherwise proven: it authenticated, derived L2 API creds, signed, and posted. It would work from
an allowed region (ToS caveats aside).

## The workaround: PolyGun (custodial relayer)
**PolyGun** (polygun.xyz, Telegram `@PolyGunSniperBot`) is a third-party Polymarket trading bot.
Its relayer trades from a non-blocked context, so it **sidesteps the geoblock**. For a US user
PolyGun isn't just convenience — it's the *path to access*, and custody is the price of access.

**Custody model (verified on-chain) — the key thing to understand:**
- You deposit USDC → a PolyGun **deposit contract** → funds are **pooled** internally.
- Your balance then shows as **pUSD** inside PolyGun's UI (off-chain custodial accounting).
- The private key PolyGun gives you is a **signing/auth identity**, *not* the wallet holding
  the money — that EOA reads empty on-chain. The displayed "trading address" is an empty contract.
- **You cannot self-sweep** — the only way out is PolyGun's own withdraw. (We withdrew $14 of a
  $15 test; ~$1 stayed behind as fees/leftover.)
- pUSD = "Polymarket USD" ERC-20 (`0xc011a7e12a19f7b1f670d46f03b03f3342e82dfb`, 6 dp).

## Decoded a real PolyGun trade ($2 France-to-win-WC)
- Tx sent by PolyGun **relayer** `0xb2aadacf…01ee` → **gasless for us**.
- Calls PolyGun **router** `0xe2222d27…310f59`, method `0x3c2b4399`.
- Pays pUSD to a maker + **1% fee**, and **delivers REAL Polymarket ConditionalTokens**
  (ERC-1155 `0x4d97dcd9…`) to our PolyGun address. Positions are genuine and resolve on Polymarket.
- Implied price 0.1610 → market ~16.1% for France.

## End-to-end automation PROVEN
PolyGun has **no API** (Telegram-only, 1% fee). So we automated it with a **Telegram userbot**
(Telethon) — `polygun/pg.py` with `login / whoami / dump / send / click / buy`.

> `pg.py buy --market 558936 --side yes --amount 2 --confirm` placed a **real trade with no
> human clicking** — $2 → 12.42 France-YES shares @ 16.1c, verified on-chain (ERC-1155 delivered
> to our PolyGun address). **Code → PolyGun (Telegram) → real Polymarket position, geoblock-free.**

**Important correction:** PolyGun **market** buys have **no separate confirm step** — sending the
custom amount *immediately* fires the trade. (`pg.py buy` without `--confirm` stops *before*
sending the amount, so it's still safe; but don't assume a confirm gate exists. Use limit orders
for a true preview.)

## Live betting plan — Qatar vs. Switzerland, 3:00 PM ET (kickoff 19:00 UTC)
Use the colony's consensus to trade the match at **three points** to capture edge:
- **PRE:** run the colony → if consensus prob beats the market by more than `edge_threshold`,
  buy that side. Market (PolyGun event `e_351719`): Switzerland 82.0c / Draw 13.0c / Qatar 5.9c
  (sum 100.9c ≈ 0.9c vig — no naive buy-all arb; edge must come from better calibration).
- **DURING (in-play):** Polymarket sports markets trade live; prices overreact to goals/cards.
  Re-run the colony on the new game state and trade the gap. Largest edge window.
- **AFTER (pre-resolution):** brief window where the outcome is ~known but prices haven't snapped
  to 99/1 — opportunistic, thin, least reliable.

Wiring: `colony_harness` → `consensus_home_probability` → compare to PolyGun price → choose
side+stake → `pg.py buy`. Remaining piece: a tiny `execute_forecast()` + a name→market-id resolver.

## Direct-CLOB vs PolyGun (the trade-off)
| | Direct CLOB (`py-clob-client`) | PolyGun |
|---|---|---|
| Custody | **Self** (keys never leave us) | **Custodial** (funds pooled in PolyGun) |
| US access | **Blocked** (403 geoblock) | **Works** (relayer) |
| Plumbing | We manage USDC.e + allowances + signing | Telegram userbot, less plumbing |
| Settlement | USDC.e on Polygon | pUSD → real ConditionalTokens |

**USDC token gotcha (cost us time):** Polymarket settles in **USDC.e** (`0x2791Bca1…`), but our
treasury held **native USDC** (`0x3c499c54…`) → CLOB saw balance 0. Fix = swap native→USDC.e
(Uniswap v3 0.01% pool; `swap_to_usdce.py` works). Polymarket is **mainnet-only** (Polygon, no
testnet) — every "test trade" is a tiny **real** order, hence the 3-guard safety model on
`place_test_trade.py` (dry-run default + `--execute` + notional cap).

## Safety / classifier note
The assistant can drive all navigation and decode steps, but actual **money clicks are
classifier-gated** — it executes a trade only on explicit, specific user authorization
("do the $X bet on <side> now").

*Secrets note: all PolyGun/Polymarket signing keys live gitignored in `polymarket/.env` and
`polygun/`-side config — none are reproduced here. Addresses shown are public on-chain testnet/
mainnet identifiers.*
