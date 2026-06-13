# Worldcoin / AgentKit — Build Learnings (2026-06-12/13)

*What we proved about World ID + AgentKit, and the architecture we locked in as a result.
Companion to the plain-English Worldcoin doc; this one is the engineering record.*

## What AgentKit is
AgentKit (Beta) is an extension of World's **x402** payment protocol. Its job: let a server
tell **human-backed agents** apart from anonymous bots. A real human vouches for an agent
wallet; the server can then resolve that agent to an anonymous human identifier ("humanId")
at request time and apply access / payment rules.

- Docs: https://docs.world.org/agents/agent-kit/integrate
- CLI: `npx -y @worldcoin/agentkit-cli` (agentkit@0.1.0) — commands `register <address>`,
  `status <address>` (+ mcp/skills helpers).

## The two identities (the thing that confused us, now clear)
1. **Agent wallet** (private key + address): a normal EVM keypair. *Not* issued by Worldcoin —
   you generate it yourself (`cast wallet new`). It signs the agent's requests (eip191).
2. **Your World ID** (World App): never stored in a `.env`, no API key. Used **live** at
   registration time — you approve in the World App on your phone. That approval is what binds
   an agent address to *you*, a real human.

## What we actually did
- Generated throwaway test keypairs (gitignored in `worldcoin/test/`). Not for real funds.
- Ran `status` before registering → `registered: false, humanId: null`.
  Contract `0xA23aB2712eA7BBa896930544C7d6636a96b944dA` (AgentBook), network `eip155:480`
  (World Chain — registration lands there).
- Adil ran `register <address>`, approved in World App: "worked and was easy."
- Post-register `status` confirmed `registered: true` with a humanId — **Adil's anonymous
  human identifier**, our reference point.

## CLI facts learned
- `register` defaults to `--auto` (submits to relay `https://x402-worldchain.vercel.app`).
- `register --manual` prints the call data instead of submitting (inspect what's signed).
- `register` has **no private-key flag**: registration proves a *human* vouches; it does not
  use the agent's private key.
- `status` is a read-only AgentBook lookup → `{ registered, humanId, contract, network }`.
- `API_URL` env var overrides the relay base URL.
- Each `register` opens its **own** verification session (unique link). A session must be
  approved in the World App for *that* link; an unapproved session times out
  (`VERIFICATION_FAILED`). Claude can run the command, but the phone approval is Adil's.

## The scaling problem — "what if we need 100 agents?"
Registering 100x is the **wrong** model, for two reasons:
1. 100 interactive World App approvals (human proof is per-registration).
2. Every address *you* register resolves to the **same** humanId, because there is one of you.
   100 registrations = 1 human backing 100 wallets, not 100 verified humans. The gate counts
   usage per (endpoint, humanId), so human-ness is **pooled**, not per-wallet.

## The one-human invariant — PROVEN LIVE (2026-06-13)
We registered a **second** throwaway wallet, Adil approved it, and `status` returned the
**exact same humanId** as the first wallet. Two different wallets, one human, one humanId.

> **One human = one humanId, across ALL their wallets — a one-way hash tying every wallet you
> register back to the single you. No Sybil cheat exists, by design.**

This is now empirically confirmed, not just inferred.

## Server-side gate mechanics (confirmed)
Request flow: hit endpoint → `402` challenge → agent signs a CAIP-122 message (eip191) with
its wallet → server verifies the signature, looks up **that signing wallet** in AgentBook →
resolves to a humanId → applies policy. **The only thing the server keys on is the signing
wallet address.** AgentKit's built-in free-trial limit (3 uses / endpoint / humanId) is pooled
per human — but mostly irrelevant for us, because Colony runs its **own** x402 ClickHouse gate
with its own policy.

## Architecture we locked in
World ID verification happens **once per real human** → yields a humanId → that humanId **is**
the "verified lineage" badge, stamped into ENS / colony state. We register **roots, not ants**:
recruit N humans → N verified lineage roots (N distinct humanIds). Children inherit "verified"
through *our* bookkeeping (colony state + ENS records), never by replaying World ID. When an
ant must prove human-backing to a gated endpoint, it signs with its lineage's registered
wallet — one tap per human, not per ant. (Matches plan §3: "verification attaches to a lineage,
not each ant.")

## Still to validate later
- **Shared-key signing test:** register one wallet, then sign two different agent requests
  with that key against a gated endpoint → confirm the server accepts both and reports the same
  humanId. (We've proven same-human across *registrations*; still want to prove one key can
  *sign* for many agent contexts at request time.)
- Deep-read `x402/DOCS.md` + `skills/agentkit-x402/SKILL.md` for the exact verifier
  (`createAgentBookVerifier`) and `tryIncrementUsage(endpoint, humanId, limit)` semantics.
- Reconcile World Chain (`eip155:480`) with Arc, where Colony settles money (the chain seam).
- Map humanId → ENS lineage root record.

*Secrets note: test keypairs and any humanId values live gitignored under `worldcoin/test/`;
nothing secret is reproduced here.*
