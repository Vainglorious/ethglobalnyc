# Dynamic — Wallet Architecture (MPC / WaaS) Learnings (2026-06-13)

*Can we stand up many ant wallets fast on Arc testnet? Yes. What signing costs, and how Dynamic
composes with Arc + Unlink. Engineering record.*

## Goal
Evaluate Dynamic (dynamicauth.com) for wallet architecture — specifically, spin up ~10 wallets
fast on testnet for use on Arc (EVM, chain 5042002).

## Key architecture finding — this env uses **V3 (MPC / WaaS)** wallets
- The deprecated `/environments/{env}/embeddedWallets` endpoint (V2/Turnkey) is **rejected** here:
  "Cannot create a Turnkey embedded wallet in an environment configured for V3 wallets."
- Working server-side endpoint for V3 pregenerated wallets:
  `POST {base}/environments/{ENV_ID}/waas/create` with `Authorization: Bearer <API_KEY>`,
  body `{ "identifier": "<email>", "type": "email", "chains": ["EVM"] }` → 201, returns an
  eip155 EVM address, `version "V3"`, `thresholdSignatureScheme "TWO_OF_TWO"`.
- **V3 = MPC:** key shares held by Dynamic (2-of-2). **No raw private key is returned.** Signing
  happens *through* Dynamic (API/SDK), not via a local key — the big contrast with our
  cast-generated treasury wallet (where we hold the key).

## The 10-wallet test — PASSED
Created **10 V3 MPC EVM wallets in parallel in ~3.55 s (~355 ms/wallet)**
(`dynamic/create-wallets.mjs`). All eip155 addresses, usable on Arc testnet. So Dynamic can
pregenerate many ant wallets fast, server-side, from one API key — good for "tens of ants" and
beyond. Each wallet ties to an identifier a real human could later **claim** by logging in.

## Server-side signing works — two paths
In `@dynamic-labs-wallet/node-evm`:
1. **Delegated** (`delegatedSignTransaction/Message/TypedData`): needs `walletId` + `walletApiKey`
   + `keyShare` from a `wallet.delegation.created` flow. For wallets a *user* delegates to us.
2. **Developer-created** (`DynamicEvmWalletClient`): **we** create the wallet and hold the key
   share, so we can sign immediately — no delegation. **This is what we used.**

Recipe (developer-created): `authenticateApiToken(apiKey)` → `createWalletAccount({...})` →
`getWalletClient({ walletMetadata, password, externalServerKeyShares, chainId:5042002, rpcUrl })`
returns a **viem WalletClient** that signs via MPC — usable for Arc txs *and* as Unlink's
`evm.fromViem` provider. Proven: created an MPC wallet in ~2.2 s and signed real Arc txs.

## Combined cross-product route — ALL HOPS PROCESSED
`dynamic/combined-route.mjs`:
```
A treasury 0x1be3…2D8F  --3 USDC native (Arc)-->        B Dynamic MPC 0xDF53…E984
B  --depositWithApproval 2 USDC (B signs via MPC)-->     C Unlink (private)
C  --Unlink private transfer 1 USDC-->                   D Unlink (private)
Result: deposit processed, transfer processed; C private 2 USDC, D private 2 USDC.
```
The **same** Dynamic MPC walletClient both sends Arc USDC *and* acts as Unlink's EVM provider for
the deposit. **Dynamic + Arc + Unlink compose cleanly.**
(Arc note: native USDC (18 dp) and the `0x3600…` ERC-20 (6 dp) are the *same* balance — funding
with native USDC also gives spendable ERC-20 USDC + gas. Verified on-chain.)

## Wallet-model takeaway for Colony
A **hybrid is viable and proven:** treasury (local key) funds Dynamic MPC wallets (managed, no
key to leak, **claimable by humans → ties to Worldcoin verified lineages**), which can push USDC
into Unlink's private layer. Decide per-ant: **Dynamic MPC for verified/human roots, local cast
keys for cheap ephemeral ants.**

## Critical lesson learned (stranded funds)
- **SDK-created** (developer) wallets: we can sign for them — but `combined-route.mjs` makes a
  fresh wallet each run and does **not persist** `walletMetadata` + `externalServerKeyShares`, so
  there's no handle to reload it. **Persist those (encrypted) at creation** or funds are stranded.
- **Pregenerated REST** (`waas/create`) wallets: Dynamic holds both key shares, so spending needs
  the **delegation flow set up first**. ~2 USDC was deliberately parked in such wallets as not
  worth recovering vs. the healthy treasury.

## Still open
- Pregenerated REST wallets (need delegation) vs SDK-created (sign immediately) — decide which we
  use for ants.

*Secrets note: the Dynamic API key (`dyn_…`) lives gitignored in `dynamic/.env`; only the
non-secret Environment/Org IDs and public EVM addresses appear here.*
