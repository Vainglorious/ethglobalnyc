# Unlink — saved reference

Source: https://docs.unlink.xyz (+ the clean `.md` pages, e.g. /quickstart.md,
/accounts-and-keys.md, /transfer.md, /faucet.md, /supported-chains.md). Saved 2026-06-13.
Full LLM index: https://docs.unlink.xyz/llms.txt

## Concept
"Build private applications on blockchains." Own/send/receive/interact with contracts
without exposing balances, tokens, amounts, or history. It's a smart contract on an existing
EVM chain (no separate chain, no bridge).

Flow stages:
- Public wallet (your 0x EVM address)
- Unlink contract (holds the private account)
- Private account ("unlink1..." address) — transfers happen here, invisibly
- Public recipient (for withdrawals)

## Four operations
- depositWithApproval() — public wallet -> Unlink contract
- transfer()            — unlink1... -> unlink1..., private
- withdraw()            — Unlink contract -> public EVM address
- execute()             — call contracts from a private account (needs seed-backed account)

## SDK packages
- @unlink-xyz/sdk/browser  — browser/MetaMask, non-custodial
- @unlink-xyz/sdk/client   — server/custodial (Node, our own keys)
- @unlink-xyz/sdk/admin    — backend registration + auth tokens (holds apiKey)
- @unlink-xyz/sdk/crypto   — account constructors (alt import path)

Install (canary channel): `npm install @unlink-xyz/sdk@canary`

## Accounts & keys
Constructors: fromMnemonic, fromSeed, fromEthereumSignature, fromMetaMask, fromKeys.
NO fromPrivateKey. fromKeys can transfer/withdraw but NOT execute; seed-backed ones do all.

```ts
const acct = account.fromMnemonic({ mnemonic, appId, chainId: 84532 });
const address = await acct.getAddress();   // "unlink1..."
```
Note: "Deriving with the wrong chainId produces a different account." appId + chainId matter.

## Custodial (Node) client setup
```ts
import { createUnlinkAdmin } from "@unlink-xyz/sdk/admin";
import { account, createUnlinkClient } from "@unlink-xyz/sdk/client";

const admin = createUnlinkAdmin({ environment: "base-sepolia", apiKey: process.env.UNLINK_API_KEY });

const unlinkAccount = account.fromMnemonic({ mnemonic });
const unlinkAddress = await unlinkAccount.getAddress();

const client = createUnlinkClient({
  environment: "base-sepolia",
  account: unlinkAccount,
  register: (payload) => admin.users.register(payload),
  authorizationToken: { provider: () => admin.authorizationTokens.issue({ unlinkAddress }) },
});
await client.ensureRegistered();
```

## Transfer
```ts
const tx = await client.transfer({
  recipientAddress: "unlink1...",   // single mode
  token: "0xTokenAddress",          // ERC-20 contract address
  amount: "250000000000000000",     // smallest unit (string), NOT decimals-adjusted
});
const confirmed = await tx.wait();  // confirmed.status: "processed" | "failed"
```
Batch mode: pass `transfers: [{ recipientAddress, amount }, ...]` instead of recipientAddress/amount.
Signs with the spending key of the account bound to the client. Returns a TransactionHandle.

## Faucet (testnet funding)
- client.faucet.requestTestTokens({ token, amount })    — mint ERC-20 to an EVM wallet
- client.faucet.requestPrivateTokens({ token, amount }) — shielded tokens into the Unlink account
Optional: evmAddress / unlinkAddress (default caller), amount (wei decimal string, capped).
The `token` is a test token configured for your environment (from dashboard project config) —
docs don't hardcode addresses.

## Balances / reading
```ts
const { balances } = await client.getBalances();
```
See also /reading-data.md, /errors.md, /execute.md, /withdraw.md, /deposit.md.

## Supported chains (all testnets here)
| environment | chainId | notes |
|---|---|---|
| arc-testnet | 5042002 | USDC = native gas; faucet.circle.com — COLONY'S CHAIN |
| base-sepolia | 84532 | ETH faucet: alchemy.com/faucets/base-sepolia |
| ethereum-sepolia | 11155111 | |
| monad-testnet | 10143 | |

## Credentials
- UNLINK_API_KEY — from dashboard.unlink.xyz (org -> project -> API Keys). Backend-only.
- appId — browser/account derivation (from dashboard).
- test token address — from project/environment config.
- environment + chainId must match.

## Open questions to confirm against the live SDK
- Exact import path for `account` (sdk/client vs sdk/crypto — docs show both).
- The test-token value shape (raw 0x address vs a config object).
- arc-testnet faucet/token specifics (USDC native gas) vs base-sepolia.
