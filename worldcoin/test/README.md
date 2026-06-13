# worldcoin/test — keypair feasibility test

Throwaway scratch space to prove out the World App agent-whitelisting flow before we
build the real rail. Nothing here is for real funds.

## What's here

- `test-agent-keypair.json` — a throwaway EVM keypair generated with `cast wallet new`.
  **GITIGNORED** (see ../.gitignore) so the private key never gets committed.

  Generated on 2026-06-12 with:
  ```bash
  cast wallet new --json
  ```

  A keypair is just an Ethereum account — not issued by Worldcoin. The same address
  works on World Chain (`eip155:480`) and Base (`eip155:8453`).

## The feasibility test (what Adil is verifying)

Goal: confirm that this address can be **whitelisted / registered as human-backed**
through the World App, while logged in as a registered World user.

```bash
# from repo root, with @worldcoin/agentkit-cli available
npx @worldcoin/agentkit-cli register 0x570A499afb5E0D32Abf748e4FE299e0F33A82d50
# -> should prompt the World App verification flow; approve on phone

npx @worldcoin/agentkit-cli status 0x570A499afb5E0D32Abf748e4FE299e0F33A82d50
# -> should report the address as registered / human-backed
```

What success looks like: after approving in World App, `status` shows the address is
registered, and AgentKit can resolve it to your anonymous human identifier.

## Things to watch / confirm during the test

- [ ] Does `register` actually pop a World App prompt for a registered user? (our core assumption)
- [ ] Does it need testnet gas / funds on the agent address to submit the registration tx,
      or does the hosted relay cover it? (docs say "hosted relay" — verify.)
- [ ] What does `status` return as the human identifier, and is it stable across multiple
      addresses we register? (expected: SAME humanId for all — that's the one-human rule.)
- [ ] Which chain the registration lands on (World Chain vs Base) and whether that needs to
      reconcile with Arc, where Colony settles money. (see ../docs/agent-kit-integrate.md)

## Reminder (the Colony-relevant catch)

Every address you register resolves to the SAME anonymous human id (you). One human =
one verified lineage root. You can whitelist many agent wallets, but they all share your
single humanId — you can't mint distinct verified humans. (plan §3)
