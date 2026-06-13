# Arc — testnet network + treasury

Arc is Circle's blockchain for stablecoin payments; **USDC is the native gas token**. Colony
settles all money on Arc testnet. https://www.arc.io/ecosystem · docs https://docs.arc.io

## Testnet network details
| Field | Value |
|---|---|
| Chain ID | `5042002` |
| RPC (primary) | `https://rpc.testnet.arc.network` (also Blockdaemon / dRPC / QuickNode) |
| WebSocket | `wss://rpc.testnet.arc.network` |
| Native gas token | USDC (18 decimals) |
| USDC ERC-20 | `0x3600000000000000000000000000000000000000` (6 decimals) |
| EURC | `0x89B50855Aa3bE2F677cD6303Cec089B5F319D72a` |
| Permit2 | `0x000000000022D473030F116dDEE9F6B43aC78BA3` |
| Explorer | https://testnet.arcscan.app |
| Faucet | https://faucet.circle.com (USDC + EURC) |

CCTP/Gateway contracts are in docs.arc.io `references/contract-addresses`.

## Treasury wallet (our single source of test USDC)
- Address: `0x1be3F1edA4C654BdF3bDcF973EF861346EA52D8F`
- Private key: in `arc/.env` (`ARC_TREASURY_PRIVATE_KEY`) — **gitignored**, testnet only.
- Funded: **20 USDC** (verified on-chain). Confirmed via `cast balance` + ERC-20 `balanceOf`.

## Funding model — NO MORE FAUCETS
The 20 USDC treasury is enough for the whole hackathon. **Fund everything downstream by
transferring/depositing from the treasury**, not via faucets. Proven already: we deposited
treasury USDC into Unlink and did a private 1 USDC transfer (see
`notes/2026-06-13-treasury.txt` + `unlink/deposit-and-transfer.mjs`).

## Quick checks
```bash
RPC=https://rpc.testnet.arc.network
cast chain-id --rpc-url $RPC                                   # 5042002
cast balance 0x1be3F1edA4C654BdF3bDcF973EF861346EA52D8F --rpc-url $RPC   # native (18dp)
cast call 0x3600000000000000000000000000000000000000 \
  "balanceOf(address)(uint256)" 0x1be3F1edA4C654BdF3bDcF973EF861346EA52D8F --rpc-url $RPC  # ERC-20 (6dp)
```

## Ecosystem partners relevant to us
- **Circle / Arc** — the chain + faucet.
- **Dynamic** — listed Arc wallet partner; we use it to pregenerate EVM wallets (`../dynamic`).
- **Unlink** — privacy layer; runs on arc-testnet too (`../unlink`).

## Notes
- 1 USDC = `1000000` via the ERC-20 (6 decimals), but `1000000000000000000` as native gas (18dp).
  Watch which interface a given API expects.
