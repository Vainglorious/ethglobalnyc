# Dynamic — wallet infrastructure (WaaS)

Exploring **Dynamic** (dynamicauth.com) for Colony's wallet architecture: can we pre-generate
many EVM wallets fast, server-side, for use on Arc testnet? **Answer: yes** (10 in ~3.5s).

## Account / config (in `.env`, gitignored)
- Environment ID `cf59a816-223e-4f99-a716-29b08c751210`, Org `0708a2f4-...`
- API key `dyn_…` (server-side secret), API base `https://app.dynamicauth.com/api/v0`
- JWKS endpoint for verifying Dynamic-issued JWTs (auth side, not used for wallet creation).

## This environment uses V3 (MPC / WaaS) wallets
Important: the old `/embeddedWallets` (V2/Turnkey) endpoint is **rejected** here. V3 wallets are
**MPC**: key shares are held by Dynamic (2-of-2 threshold). **No raw private key is returned** —
signing happens *through* Dynamic, not via a local key. (Contrast: our Arc treasury is a local
`cast` key we hold ourselves.)

## Server-side wallet creation (works with the API key)
```
POST {base}/environments/{ENV_ID}/waas/create
Authorization: Bearer <DYNAMIC_API_KEY>
Content-Type: application/json
{ "identifier": "user@example.com", "type": "email", "chains": ["EVM"] }
```
→ `201`, returns `user.verifiedCredentials[].address` (an `eip155` EVM address, version `V3`).
The wallet can later be **claimed** by a human who logs in with the same identifier.

## The 10-wallet test (`create-wallets.mjs`)
```bash
set -a && source .env && set +a && node create-wallets.mjs 10
```
Result: **10/10 V3 MPC EVM wallets in ~3550 ms (~355 ms/wallet, parallel).** EVM/eip155 → usable
on Arc testnet (chain 5042002). Addresses recorded in `notes/2026-06-13-dynamic-wallets.txt`.

## Why this matters for Colony
- Fast, server-side pregeneration of ant wallets with one API key — scales past "tens of ants."
- Each wallet is claimable by a real human via its identifier — interesting for the verified
  lineage story (ties to Worldcoin personhood).
- **Tradeoff:** MPC wallets have no local key, so signing Arc txs requires a Dynamic signing
  call. Local `cast` keys sign instantly but we manage the secrets. Likely a hybrid: Dynamic for
  human-claimable/verified roots, local keys for ephemeral ants.

## Open / next
- [ ] Find + test the V3 **signing** endpoint (sign an Arc tx/message for a pregen wallet).
- [ ] Fund a Dynamic wallet from the treasury; confirm it holds/moves USDC on Arc.
- [ ] Decide the ant wallet model (Dynamic MPC vs local keys vs hybrid).

## Files
- `create-wallets.mjs` — pre-generate N wallets and time it.
- `.env` / `.gitignore` — credentials (gitignored).
