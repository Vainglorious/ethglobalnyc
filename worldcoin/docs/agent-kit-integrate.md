# World Agent Kit — Integration (saved reference)

Source: https://docs.world.org/agents/agent-kit/integrate
Saved: 2026-06-12. This is our working copy of the integration notes; check the live
page for updates (AgentKit is in Beta).

## What it is

**AgentKit (Beta)** is an extension of the **x402 payment protocol** that lets a website
**distinguish human-backed agents from bots and scripts**. Legitimate agents get access to
API endpoints; scalpers / spam / scripts are blocked. It validates that an agent is operated
by a real human before granting access or applying payment rules.

> Why this matters for Colony: this is the Worldcoin "personhood at the lineage root" piece
> AND it speaks x402, the same protocol the ClickHouse gate uses. One verified human registers
> agent wallets; AgentKit resolves each request to an anonymous human identifier. That is our
> "one proof per human, attached to a lineage, not per-ant" rule, made concrete.

## Install

```bash
npm install @worldcoin/agentkit
```

Other packages used in the reference implementation:
- `@worldcoin/agentkit-cli`  — agent registration / status
- `@x402/hono`               — Hono server wrapper
- `@x402/core/http`          — HTTP facilitator client
- `@x402/evm/exact/server`   — EVM payment scheme

## Key config values seen in the docs

The page does NOT give explicit env-var names; these are the values the code references:

| Concept | Value / example |
|---|---|
| Agent wallet address | the agent's signing address (registered on World Chain) |
| Chain ID (World Chain) | `eip155:480` |
| Chain ID (Base) | `eip155:8453` |
| Facilitator URL (default) | `https://x402-worldchain.vercel.app/facilitator` |
| USDC token (World Chain) | `0x79A02482A880bCE3F13e09Da970dC34db4CD24d1` |
| Payment recipient | `payTo` variable (server's receiving address) |

No API keys / secrets are explicitly listed in this section. Verification is done through the
**World App flow**, not an API key.

## Agent verification / registration flow

Register an agent wallet address (this is where the human proof happens):

```bash
npx @worldcoin/agentkit-cli register <agent-address>
npx @worldcoin/agentkit-cli status   <agent-address>
```

Registration does three things:
1. looks up the next nonce for the agent address;
2. **prompts the World App verification flow** (the human — you — verifies);
3. submits the registration transaction to World Chain via a hosted relay.

After that, AgentKit can resolve the agent to an **anonymous human identifier** at request time.

## Code sketches

Client (agent side):
```typescript
import { createAgentkitClient } from '@worldcoin/agentkit'

const agentkit = createAgentkitClient({
  signer: {
    address: agentWallet.address,
    chainId: 'eip155:8453',           // or 'eip155:480' for World Chain
    type: 'eip191',
    signMessage: message => agentWallet.signMessage(message),
  },
})

const response = await agentkit.fetch('https://api.example.com/data')
```

Server (Hono):
```typescript
const agentBook = createAgentBookVerifier()
const storage = new InMemoryAgentKitStorage()

const hooks = createAgentkitHooks({
  agentBook,
  storage,
  mode: { type: 'free-trial', uses: 3 },   // default; use persistent storage in prod
})
```

Production storage implements `AgentKitStorage`:
`tryIncrementUsage(endpoint, humanId, limit)`, `hasUsedNonce(nonce)`, `recordNonce(nonce)`.

## Confirmed live via the CLI (2026-06-12)

Ran `@worldcoin/agentkit-cli` (v `agentkit@0.1.0`) directly:

- **AgentBook contract:** `0xA23aB2712eA7BBa896930544C7d6636a96b944dA`
- **Network:** `eip155:480` — registration lands on **World Chain** (answers the chain question).
- `register <address>` defaults to `--auto` (submits to relay `https://x402-worldchain.vercel.app`);
  `--manual` prints the call data instead of submitting. **No private-key flag** — registration
  proves a *human* vouches for the address (World ID proof), it does not use the agent's key.
- `status <address>` is a read-only AgentBook lookup → `{ registered, humanId, contract, network }`.
- `API_URL` env var overrides the relay base URL.
- Baseline for our test address `0x570A...2d50`: `registered: false, humanId: null`.

The CLI also exposes `mcp add` / `skills add` / `--mcp` (can run as an MCP stdio server) — may be
useful later if we want agents to call register/status as a tool.

## Open questions to resolve from the live docs / portal

- [ ] Exact env-var names the kit expects (none listed here — likely we define our own).
- [ ] Which chain: World Chain (`eip155:480`) vs Base (`eip155:8453`) — and does this need to
      agree with Arc, where Colony settles money? (possible seam — confirm.)
- [ ] Does registration need anything from the World developer portal, or only World App?
- [ ] How `humanId` (anonymous human identifier) maps onto our ENS lineage records.
