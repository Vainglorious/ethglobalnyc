// create-wallets.mjs — pre-generate N Dynamic V3 (MPC/WaaS) embedded wallets, server-side.
//
// Run:  set -a && source .env && set +a && node create-wallets.mjs [N]
// (No dotenv dependency — reads process.env; source .env first.)
//
// These are V3 MPC wallets: key shares are held by Dynamic (2-of-2 threshold). There is NO
// raw private key returned — signing happens through Dynamic, not a local key. EVM/eip155
// addresses, so usable on Arc testnet (chain 5042002).

const base = process.env.DYNAMIC_API_BASE;
const env = process.env.DYNAMIC_ENVIRONMENT_ID;
const key = process.env.DYNAMIC_API_KEY;
const N = Number(process.argv[2] || 10);
const url = `${base}/environments/${env}/waas/create`;
const runTag = Date.now();

async function createWallet(i) {
  const identifier = `colony-ant-${i}-${runTag}@colony.test`;
  const r = await fetch(url, {
    method: "POST",
    headers: { Authorization: "Bearer " + key, "Content-Type": "application/json" },
    body: JSON.stringify({ identifier, type: "email", chains: ["EVM"] }),
  });
  let j = {};
  try { j = await r.json(); } catch {}
  const vc = (j.user?.verifiedCredentials || []).find((c) => c.chain === "eip155")
          || j.user?.verifiedCredentials?.[0];
  return {
    i, status: r.status, identifier,
    userId: j.user?.id,
    address: vc?.address,
    version: vc?.wallet_properties?.version,
    error: j.error,
  };
}

const t0 = Date.now();
const results = await Promise.all(Array.from({ length: N }, (_, k) => createWallet(k + 1)));
const ms = Date.now() - t0;

for (const r of results) {
  console.log(`#${String(r.i).padStart(2)} ${r.status} ${r.address || "(no address)"} ${r.version || ""}${r.error ? "  ERR: " + r.error : ""}`);
}
const ok = results.filter((r) => r.address).length;
console.log(`\nCreated ${ok}/${N} wallets in ${ms} ms  (~${(ms / N).toFixed(0)} ms/wallet, parallel)`);

// Emit a JSON array of {i, address, userId} for downstream use.
console.log("\nADDRESSES_JSON " + JSON.stringify(results.map((r) => ({ i: r.i, address: r.address, userId: r.userId }))));
