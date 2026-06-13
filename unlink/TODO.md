# Unlink — TODO

## ✅ DONE: 1 USDC A->B private transfer (2026-06-13)
Proven end-to-end on arc-testnet with REAL USDC (`unlink/deposit-and-transfer.mjs`):
treasury 0x1be3...2D8F --depositWithApproval 2 USDC--> A (private) --transfer 1 USDC--> B.
Result: A 2→1 USDC, B 0→1 USDC, both `processed`.
- Token: Arc USDC ERC-20 `0x3600000000000000000000000000000000000000` (6 decimals).
- Env: `arc-testnet`. The Unlink faucet does NOT serve Arc USDC — we **deposit from the treasury**.

## Funding model (decided): NO faucets
The 20 USDC treasury is enough for the whole hackathon. Fund Unlink accounts by **depositing
from the treasury** (`depositWithApproval`), not via faucet. Do not chase faucets.

## Later
- [ ] Evaluate Unlink as a **privacy layer for Colony ant USDC on Arc** (both live on arc-testnet,
      chain 5042002). Private ant-to-ant stakes/inheritance vs. fully-public transfers.
