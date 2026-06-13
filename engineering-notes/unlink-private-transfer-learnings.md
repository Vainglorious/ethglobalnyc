# Unlink — Private Transfer Learnings (2026-06-13)

*Goal: confirm a single ~1 USDC **private** transfer between two test wallets works. Status:
**DONE — it works end-to-end on arc-testnet.** This is the engineering record.*

## What Unlink is
"Build private applications on blockchains." A smart contract on an existing EVM chain (no
separate chain, no bridge). You deposit ERC-20 tokens in, transfer them **privately** between
Unlink accounts (no on-chain balances/amounts/history), then withdraw back out.

- Docs: https://docs.unlink.xyz (clean `.md` pages + `https://docs.unlink.xyz/llms.txt`)
- Four operations: `depositWithApproval()` in, `transfer()` private, `withdraw()` out,
  `execute()` to call contracts (needs a seed-backed account).

## Why it matters for Colony
Unlink supports **arc-testnet (chainId 5042002)** — the same Arc chain Colony settles money on
(USDC = native gas there). So Unlink is a candidate privacy layer for ant-to-ant USDC (private
stakes / inheritance).

## SDK facts (verified against the installed SDK, `@unlink-xyz/sdk@0.3.0-canary.598`)
- Install: `npm install @unlink-xyz/sdk@canary`.
- Packages: `/browser` (MetaMask), `/client` (custodial Node — what we use), `/admin`
  (apiKey + registration + auth tokens), `/crypto` (account constructors).
- Account constructors: `fromMnemonic`, `fromSeed`, `fromEthereumSignature`, `fromMetaMask`,
  `fromKeys`. **No `fromPrivateKey`** — so we use mnemonics.
- `account.fromMnemonic` takes **only** `{ mnemonic, accountIndex? }` — no appId/chainId.
  (appId/chainId are bound only in `fromMetaMask` / `fromEthereumSignature`.) So the mnemonic
  flow does **not** need an appId — that early blocker is gone.
- `transfer({ token, amount, recipientAddress })` → handle → `await tx.wait()` → `{ status }`
  (`"processed"` | `"failed"`). `amount` is smallest-unit **string** (not decimals-adjusted).
- `faucet.requestPrivateTokens({ token, amount? })` funds the Unlink account (shielded);
  `requestTestTokens()` mints ERC-20 to an EVM wallet.
- `balanceOf(token)` → smallest-unit string (`null` when zero). `getAddress()` → `"unlink1…"`.

## Supported testnets
`arc-testnet` 5042002 (USDC native gas; faucet.circle.com — Colony's chain) ·
`base-sepolia` 84532 · `ethereum-sepolia` 11155111 · `monad-testnet` 10143.

## How we got to a working transfer (the blockers, in order)
1. **API key** — obtained, saved gitignored in `unlink/.env`. Authenticates fine.
2. **Tenant provisioning is environment-specific.** Probing with the key, only **arc-testnet**
   returned a "belongs to a tenant" signal (a different, more specific error than the other
   testnets' "tenant not provisioned"). → Our project is provisioned on **arc-testnet (5042002)**.
3. On arc-testnet: `account.fromMnemonic` + `createUnlinkClient` + `ensureRegistered()` → both
   wallets register OK. `getEnvironmentInfo()` returns chain_id 5042002, a pool address,
   permit2, execution_account — **but no token list.**
4. **Token blocker.** `faucet()` and `transfer()` both need a `token` (ERC-20 address) that the
   SDK wouldn't surface. Resolved from `docs.arc.io`: Arc testnet USDC is
   `0x3600000000000000000000000000000000000000` (6 decimals).
5. **Faucet won't dispense Arc USDC** ("token not supported by faucet"). So instead of
   faucet-funding, we **deposit real USDC from the funded Arc treasury**, then transfer.

## The working run
Script: `unlink/deposit-and-transfer.mjs` — uses a viem `walletClient` over the Arc RPC +
`evm.fromViem({ walletClient, publicClient })` to sign on-chain from Node, then
`depositWithApproval({ token, amount, evm })`, then `transfer({...})`.

```
Treasury (20 USDC)  --depositWithApproval 2 USDC-->  Wallet A   : status processed
Wallet A private balance: 2 USDC
transfer 1 USDC  A --> B                                          : status processed
Wallet A after: 1 USDC | Wallet B after: 1 USDC      <-- 1 USDC moved privately
```

## Still open
- Whether arc-testnet's **native** USDC can be transferred via Unlink directly (Unlink moves
  ERC-20s; a native gas token may need a wrapped/test ERC-20 instead — the deposit path sidesteps
  this for now).
- `token` is confirmed a string (ERC-20 address) per `SingleTransferParams.token: string`.

*Secrets note: the test wallet mnemonics/private keys and the Unlink API key live gitignored in
`unlink/.env` — none are reproduced here.*
