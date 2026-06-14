# Set up `worldcolony.eth` to showcase the colony's trades — task brief

**Paste this whole file into a Claude (web) chat and ask it to walk you through doing it on app.ens.domains.**

## Goal
Make my **mainnet** ENS name **`worldcolony.eth`** resolve to the wallet that holds
my project's live Polymarket trades, and add text records that tell the story — so a
hackathon judge can resolve the name and see the colony's real betting activity.

## Facts
- ENS name: **`worldcolony.eth`** (Ethereum **mainnet**).
- I control the **owner wallet**: `0x9e91D1E6cbc1341d7a8235214491BA1521dfa9a4` (connect this in app.ens.domains).
- The **trades wallet** (the target): `0xe9E32Ca24aa1eF725F650b5489281FE621363AA9`
  - This is a PolyGun custodial address on **Polygon** that holds the positions
    (open France-YES ~24.8 shares + pUSD) and is the recipient of every trade.
  - It's a valid EVM address, so the ENS **ETH address record** can point at it; a
    judge then views it on **polygonscan.com** for the trades.
- Context: "Colony" is an evolutionary swarm of forecasting agent "ants" betting real
  money on 2026 World Cup markets (via PolyGun, because Polymarket's CLOB geoblocks the US).

## What to set on `worldcolony.eth` (app.ens.domains → Records)

1. **Resolver:** if none is set, set the **ENS Public Resolver** (one mainnet tx).

2. **Address record — ETH** (the key one; this is the showcase):
   ```
   ETH = 0xe9E32Ca24aa1eF725F650b5489281FE621363AA9
   ```

2b. **Address record — POLYGON** (optional but recommended — the trades are on Polygon):
   Records → Addresses → Add → pick **Polygon** →
   ```
   Polygon = 0xe9E32Ca24aa1eF725F650b5489281FE621363AA9
   ```
   (Under the hood: multichain setAddr(node, coinType, addr), Polygon coinType
   2147483785 = 0x80000000 | 137. Same EVM address as ETH. `.eth` names live ONLY
   on Ethereum mainnet — this just adds a Polygon address record to the same name;
   there is no separate Polygon ENS registry.)

3. **Text records** (copy/paste these key → value pairs):
   ```
   description = Colony: an evolutionary swarm of forecasting agent "ants" betting real money on the 2026 World Cup. This wallet holds the colony's live Polymarket positions (executed via PolyGun). View its trades on Polygonscan.
   url         = https://worldcolony.nyc
   notice      = Live Polymarket trades (Polygon): https://polygonscan.com/address/0xe9E32Ca24aa1eF725F650b5489281FE621363AA9
   com.github  = Vainglorious/ethglobalnyc
   avatar      = (optional — a hosted image URL or ipfs://… for the colony logo)
   ```

   > STATUS (2026-06-14): the ETH address record + all four text records above are
   > ALREADY SET and confirmed live on mainnet (`url` = https://worldcolony.nyc).
   > Only `avatar` remains unset.

4. Save / confirm the transaction(s) (mainnet gas).

## Important limitation (don't fight this)
There are two directions in ENS:
- **Forward** (`worldcolony.eth` → address): set by the name owner (me). ✅ Steps above do this.
- **Primary / reverse** (the address *displays* "worldcolony.eth"): must be set by the
  **address's own private key.** I do **NOT** control `0xe9E3…3AA9` (it's PolyGun's
  custodial contract), so I **cannot** set it as that wallet's primary name. That's
  fine — the forward record is what makes "resolve the name → see the trades" work.
  (If I want a primary name on a wallet I *do* control, I'd use the treasury
  `0xcc16bEC342794f35a32d4Ba2c76BF9D759C131eB` or the owner wallet — but those don't
  hold the trades.)

## Testnet vs mainnet (so there's no confusion)
- The per-agent subnames `root-*.colonny.eth` are on **Sepolia testnet** (a different
  name + different network). They don't interact with `worldcolony.eth` on mainnet.
- For a judge resolving in normal/mainnet ENS tools, **only `worldcolony.eth` (mainnet)
  shows up** — so it's the one to configure for the live demo.

## What I want help with
Walk me through doing the above in app.ens.domains (which buttons, setting the resolver,
adding the address + text records), and flag anything I'm missing for the ENS prize.
