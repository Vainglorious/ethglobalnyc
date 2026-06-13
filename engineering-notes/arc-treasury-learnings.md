# Arc Testnet — Treasury & Funding Model (2026-06-13)

*The single source of test USDC for the whole project, and the funding policy we decided.
Engineering record.*

## The treasury wallet
Generated 2026-06-13 with `cast wallet new` — throwaway / testnet only.

- Address: `0x1be3F1edA4C654BdF3bDcF973EF861346EA52D8F`
- Private key: stored gitignored in `arc/.env` (`ARC_TREASURY_PRIVATE_KEY`) — never committed.

Funded via the Circle faucet (faucet.circle.com): **20 USDC**. Verified on-chain:
- native balance: `20000000000000000000` (20 USDC, 18-decimal native gas)
- ERC-20 `balanceOf`: `20000000` (20 USDC, 6-decimal ERC-20 interface)

(Same USDC shown two ways — native gas token *and* ERC-20 interface.)

## Arc testnet network facts (from docs.arc.io)
| Field | Value |
|---|---|
| Chain ID | 5042002 |
| RPC (primary) | https://rpc.testnet.arc.network |
| WebSocket | wss://rpc.testnet.arc.network |
| Native gas | USDC (18 decimals) |
| USDC ERC-20 | `0x3600000000000000000000000000000000000000` (6 decimals) |
| EURC | `0x89B50855Aa3bE2F677cD6303Cec089B5F319D72a` |
| Explorer | https://testnet.arcscan.app |
| Faucet | https://faucet.circle.com (USDC + EURC) |
| Permit2 | `0x000000000022D473030F116dDEE9F6B43aC78BA3` |

(CCTP + Gateway contract addresses are in `arc/README` / docs.arc.io contract-addresses.)

## Funding model — DECIDED: no more faucets
The 20 USDC treasury is **enough for the entire hackathon**. Do not chase faucets. Fund
downstream accounts (Unlink private balances, agent/ant wallets, etc.) by **transferring or
depositing from the treasury**. The treasury is the single source of test USDC.

## Proven: Unlink private transfer funded by the treasury
The Unlink faucet does not dispense Arc USDC, so we deposit real USDC from the treasury. Full
lifecycle worked end-to-end on arc-testnet:

```
treasury  --depositWithApproval 2 USDC-->  Wallet A (private)
Wallet A  --transfer 1 USDC-->             Wallet B (private)
Result: A 2->1 USDC, B 0->1 USDC, both status "processed" — 1 USDC moved privately
```

Script: `unlink/deposit-and-transfer.mjs`. Details in the Unlink learnings doc.

## Handy snippets
Check treasury balances:
```bash
cast balance 0x1be3F1edA4C654BdF3bDcF973EF861346EA52D8F \
  --rpc-url https://rpc.testnet.arc.network

cast call 0x3600000000000000000000000000000000000000 \
  "balanceOf(address)(uint256)" \
  0x1be3F1edA4C654BdF3bDcF973EF861346EA52D8F \
  --rpc-url https://rpc.testnet.arc.network
```

*Secrets note: the treasury private key lives gitignored in `arc/.env` — not reproduced here.
The address is a disposable testnet wallet.*
