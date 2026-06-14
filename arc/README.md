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

## Internal ledger -> Arc settlement mirror

First seed agent wallets from the treasury:

```bash
cd /Users/tanguyvans/Desktop/ethglobalnyc
npm --prefix arc install
node arc/fund-agents.mjs \
  --wallet-store colony/secrets/agent-wallets.local.json \
  --amount 0.05
```

Broadcast funding only after checking the dry-run:

```bash
node arc/fund-agents.mjs \
  --broadcast \
  --wallet-store colony/secrets/agent-wallets.local.json \
  --amount 0.05 \
  --limit 10
```

The Colony harness now emits internal economy events (`balance_update`, `payment_receipt`,
`internal_stake`, `settlement_summary`). For Arc testnet, use the payment mirror to net those
balance updates per ant and produce one native-USDC transfer per wallet.

Dry-run first:

```bash
cd /Users/tanguyvans/Desktop/ethglobalnyc
npm --prefix arc install
node arc/ledger-to-transfers.mjs \
  --events colony/runs/api/<run-id>/events.jsonl \
  --wallet-store colony/secrets/agent-wallets.local.json
```

Broadcast only when the plan looks right:

```bash
node arc/ledger-to-transfers.mjs \
  --broadcast \
  --events colony/runs/api/<run-id>/events.jsonl \
  --wallet-store colony/secrets/agent-wallets.local.json \
  --scale 0.001
```

Notes:
- The script defaults to dry-run. `--broadcast` is required for transactions.
- It uses native Arc USDC transfers (`18` decimals), not the ERC-20 `6` decimal interface.
- It nets many internal ledger updates into one transfer per ant.
- Positive net deltas are treasury -> ant. Negative net deltas require a local private key for
  that ant; Dynamic MPC wallets are skipped until their signer path is wired here.
- Use `--credits-only` if you only want treasury -> ant payouts and want to skip ant debits.

## Real x402 ant-to-ant payments through Circle Gateway

This is the real payment rail for ant interactions. The seller service exposes paid HTTP resources;
Circle Gateway returns `402 Payment Required`; the buyer ant signs an EIP-3009 authorization; the
request is retried with the payment signature; Circle records a Gateway transfer.

The important design choice: **seller mode is `agent_wallet`**. The route resolves `:sellerId` from
the wallet store and uses that wallet as `payTo`. It is not treasury escrow.

Install dependencies:

```bash
npm --prefix arc install
```

Start the seller service:

```bash
node arc/x402-agent-service.mjs \
  --wallet-store colony/secrets/agent-wallets.local.json \
  --host 127.0.0.1 \
  --port 4020
```

Available paid services:

| Service | Endpoint | Price |
|---|---|---:|
| `summary` | `POST /ants/:sellerId/summary` | `0.0003` USDC |
| `audit` | `POST /ants/:sellerId/audit` | `0.0005` USDC |
| `finding_shared` | `POST /scouts/:sellerId/findings/shared` | `0.00005` USDC |
| `finding_private` | `POST /scouts/:sellerId/findings/private` | `0.00012` USDC |

Before an ant can buy resources it needs USDC in Circle Gateway. For a local EOA ant:

```bash
node arc/fund-agents.mjs \
  --broadcast \
  --wallet-store colony/secrets/agent-wallets.local.json \
  --agent ant_0001 \
  --amount 0.01

node arc/x402-gateway-deposit.mjs \
  --wallet-store colony/secrets/agent-wallets.local.json \
  --agent ant_0001 \
  --amount 0.005 \
  --balances
```

Pay another ant:

```bash
node arc/x402-agent-pay.mjs \
  --wallet-store colony/secrets/agent-wallets.local.json \
  --buyer ant_0001 \
  --seller ant_0002 \
  --service summary \
  --base-url http://127.0.0.1:4020 \
  --body-json '{"round_id":"x402_smoke","room_id":"room_alpha","topic":"Brazil vs Morocco"}'
```

API demo endpoint:

```bash
curl -X POST http://127.0.0.1:8000/x402/demo-payment \
  -H "Content-Type: application/json" \
  -d '{"buyer":"ant_0001","seller":"ant_0002","service":"finding_private"}'
```

That endpoint starts the seller service temporarily, performs a real x402 payment,
stores both buyer and seller receipts under the API runs directory, and stops the
service. This is the clean show flow: `Buy KG` moves USDC from the buyer ant to
the seller/scout ant; forecast `Stake demo` moves USDC into the Arc market
contract.

The service writes a Colony-compatible `payment_receipt` JSONL event with:

- `payment_rail: "x402_circle_gateway"`
- `network: "eip155:5042002"`
- `payer_wallet`
- `payee_wallet`
- Circle Gateway transfer UUID in `metadata.transaction`
- `gateway_amount_atomic` in 6-decimal USDC units

Query a transfer UUID:

```bash
node arc/x402-transfer-status.mjs \
  --wallet-store colony/secrets/agent-wallets.local.json \
  --agent ant_0001 \
  --transfer <gateway-transfer-uuid>
```

Smoke test completed:

- Buyer: `ant_0001` (`0x2D84caA2692bD01d4dB2bCC3be8877428E18f9f2`)
- Seller: `ant_0002` (`0x57e5eBF497e0F880Cb13713076fc4F0937e1b6e3`)
- Amount: `0.0003` USDC
- Gateway transfer: `a423015a-65c4-460e-ab2f-061b0697f825`
- Status at creation: `received`

Current limitation: Circle `GatewayClient` requires an EOA private key. The 200 Dynamic public
wallets are V3 MPC wallets and do not expose raw private keys. They can receive as seller wallets,
but buyer-side x402 from those wallets needs a Dynamic-backed `BatchEvmSigner` path rather than
`GatewayClient({ privateKey })`.

## Arc USDC forecast escrow contract

The x402 rail is for agent-to-agent services. The forecast/betting rail is a separate Arc smart
contract: ants approve/stake USDC into the contract, vote on one outcome, and correct voters claim
their winnings after settlement.

Contract source:

```text
contracts/src/ColonyForecastMarket.sol
```

Deployed Arc testnet contract:

```text
0xc40a8f2e29fe061cd4c0fe92cc73b9b43f9ada87
```

Rules:

- Group stage market: `home`, `draw`, `away`
- Knockout market: `home`, `away` only
- One ant can only vote one outcome per market, but can add more stake to the same outcome
- Settlement distributes each winner:
  `own stake + pro-rata share of losing pool after treasury fee`
- Default treasury fee: `1000 bps` = `10%` of losing pool
- If a match is canceled/no result, ants claim refunds

Build and test:

```bash
forge build
forge test -vvv
```

Deploy to Arc testnet:

```bash
node arc/forecast-market.mjs deploy \
  --treasury 0xa569696dBf9191441D045891aADCf47a919cBC1c
```

Create a market:

```bash
MARKET_KEY='worldcup:2026:brazil-morocco'
CONTRACT=0x...

node arc/forecast-market.mjs create-market \
  --contract "$CONTRACT" \
  --market-key "$MARKET_KEY" \
  --market-type three_way \
  --fee-bps 1000 \
  --metadata-uri 'worldcup:2026:brazil-morocco'
```

Stake/vote from ants:

```bash
node arc/forecast-market.mjs stake \
  --contract "$CONTRACT" \
  --wallet-store colony/secrets/agent-wallets.local.json \
  --agent ant_0001 \
  --market-key "$MARKET_KEY" \
  --outcome home \
  --amount 0.001

node arc/forecast-market.mjs stake \
  --contract "$CONTRACT" \
  --wallet-store colony/secrets/agent-wallets.local.json \
  --agent ant_0002 \
  --market-key "$MARKET_KEY" \
  --outcome draw \
  --amount 0.001
```

Settle and claim:

```bash
node arc/forecast-market.mjs settle \
  --contract "$CONTRACT" \
  --market-key "$MARKET_KEY" \
  --result home

node arc/forecast-market.mjs claim \
  --contract "$CONTRACT" \
  --wallet-store colony/secrets/agent-wallets.local.json \
  --agent ant_0001 \
  --market-key "$MARKET_KEY"
```

This gives the project two real money surfaces:

- **x402 Circle Gateway:** ant pays ant for data, summaries, audits, KG/RAG answers.
- **Arc contract escrow:** ant stakes USDC on forecast outcome and winners receive settlement.

## Ecosystem partners relevant to us
- **Circle / Arc** — the chain + faucet.
- **Dynamic** — listed Arc wallet partner; we use it to pregenerate EVM wallets (`../dynamic`).
- **Unlink** — privacy layer; runs on arc-testnet too (`../unlink`).

## Notes
- 1 USDC = `1000000` via the ERC-20 (6 decimals), but `1000000000000000000` as native gas (18dp).
  Watch which interface a given API expects.
