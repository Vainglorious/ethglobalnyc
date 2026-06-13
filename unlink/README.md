# Unlink — exploration

Investigating the **Unlink** protocol (https://docs.unlink.xyz) to understand it, with a
small testnet script that sends a private payment between two test wallets.

## What Unlink is (one paragraph)
Unlink lets you "build private applications on blockchains." It's a smart contract you
deposit ERC-20 tokens into; once inside, you can **transfer tokens privately between Unlink
accounts** without exposing balances, amounts, or history on-chain. No separate chain, no
bridging — it sits on top of an existing EVM chain. You move money in (`deposit`), move it
around invisibly (`transfer`), and move it out (`withdraw`); `execute` lets a private account
call other contracts.

## Why this is interesting for Colony (the real hook)
Unlink supports **`arc-testnet` (chain ID 5042002)** — the **same Arc network Colony settles
money on**, where USDC is the native gas token. So Unlink is a candidate **privacy layer for
the ant wallets**: ant-to-ant USDC stakes/inheritance could move privately instead of being
fully public. Not in scope for the core hackathon loop, but a natural future fit. (For this
exploration we'll likely start on `base-sepolia` since it's the simplest, best-documented testnet.)

## The model (deposit / transfer / withdraw / execute)
- `depositWithApproval()` — public wallet -> Unlink contract.
- `transfer()` — Unlink address -> Unlink address, **private**.
- `withdraw()` — Unlink contract -> any public EVM address.
- `execute()` — call smart contracts from a private account (needs a seed-backed account).

## SDK packages
- `@unlink-xyz/sdk/browser` — browser/MetaMask, non-custodial (user keys in browser).
- `@unlink-xyz/sdk/client` — server/custodial, **what we use for a Node script with our own keys**.
- `@unlink-xyz/sdk/admin` — backend: registration + auth tokens (holds the API key).
- `@unlink-xyz/sdk/crypto` — account constructors (alt import path; see docs).

## Account constructors (no `fromPrivateKey`!)
`fromMnemonic`, `fromSeed`, `fromEthereumSignature`, `fromMetaMask`, `fromKeys`.
There is **no `account.fromPrivateKey`** — for two test wallets in Node we use
`account.fromMnemonic({ mnemonic })`. (`fromKeys` can transfer/withdraw but NOT execute; the
seed-backed ones can do everything.)

**Verified against `@unlink-xyz/sdk@0.3.0-canary.598`:** `account.fromMnemonic` takes ONLY
`{ mnemonic, accountIndex? }` — **no `appId`/`chainId`** (those are bound only in the
MetaMask/EOA-signature derivations). So our flow does **not** need an `appId`.

## Supported testnets
| Environment | Chain ID | Notes |
|---|---|---|
| `base-sepolia` | 84532 | simplest; ETH faucet: alchemy.com/faucets/base-sepolia |
| `arc-testnet` | 5042002 | **Colony's chain**; USDC = native gas; faucet: faucet.circle.com |
| `ethereum-sepolia` | 11155111 | |
| `monad-testnet` | 10143 | |

## What's in this folder
- `transfer-demo.mjs` — DRAFT two-wallet private-payment script (custodial/Node flow).
- `package.json` — deps (`@unlink-xyz/sdk@canary`, `dotenv`).
- `.env.example` / `.env` — config (API key, app id, test token, two mnemonics). `.env` gitignored.
- `docs/unlink-overview.md` — saved reference of the key facts/APIs.

## How to run the test (when ready)
```bash
# 1. get an API key: https://dashboard.unlink.xyz  (org -> project -> API Keys)
# 2. generate two throwaway mnemonics:
cast wallet new-mnemonic        # run twice, or use any BIP-39 source
# 3. configure:
cp unlink/.env.example unlink/.env   # fill in API key, app id, test token, mnemonics
# 4. install + run:
cd unlink && npm install && node transfer-demo.mjs
```

## Status (verified 2026-06-13 against the installed SDK)
- SDK installed: `@unlink-xyz/sdk@0.3.0-canary.598`. `transfer-demo.mjs` was **validated against
  the real type definitions** — confirmed: `account` + `createUnlinkClient` from `/client`,
  `account.fromMnemonic({ mnemonic })`, `transfer({ recipientAddress, token, amount }) -> .wait()`,
  `faucet.requestPrivateTokens({ token, amount? })`, `balanceOf(token)`. It parses and imports load
  (dry-run stops cleanly at the missing API key). Not yet run end-to-end (needs the API key + token).
- **Remaining blockers (only 2):** `UNLINK_API_KEY` and `UNLINK_TEST_TOKEN` — both from your
  dashboard project. `appId` is **not** needed for the mnemonic flow.
- The two throwaway mnemonics are already wired into `.env` (and recorded in
  `notes/2026-06-13-unlink-exploration.txt`). Amount is set to `1000000` = 1 USDC at 6 decimals
  (bump to `1000000000000000000` if the test token is 18-decimal).
- Faucet specifics (which tokens, limits) depend on the environment's config.
