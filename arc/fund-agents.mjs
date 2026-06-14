#!/usr/bin/env node
// Fund Colony agent wallets on Arc testnet with native USDC.
//
// Default mode is DRY RUN. Use --broadcast to actually send treasury -> agent
// transfers.

import fs from "node:fs";
import path from "node:path";
import process from "node:process";

loadEnv(path.resolve("arc/.env"));

const ARC_CHAIN_ID = 5042002;
const ARC_RPC_URL = process.env.ARC_RPC_URL || "https://rpc.testnet.arc.network";
const ARC_EXPLORER = "https://testnet.arcscan.app";
const TREASURY_ADDRESS = (process.env.ARC_TREASURY_ADDRESS || "0x1be3F1edA4C654BdF3bDcF973EF861346EA52D8F").trim();
const WEI_PER_USDC = 10n ** 18n;

const arc = {
  id: ARC_CHAIN_ID,
  name: "Arc Testnet",
  nativeCurrency: { name: "USDC", symbol: "USDC", decimals: 18 },
  rpcUrls: { default: { http: [ARC_RPC_URL] } },
};

function usage() {
  console.log(`Usage:
  node arc/fund-agents.mjs --wallet-store <agent-wallets.json> --amount <USDC> [options]

Options:
  --broadcast            Send transactions. Omitted = dry-run only.
  --wallet-store <path>  Colony wallet store with agent addresses.
  --amount <USDC>        Native Arc USDC per agent, e.g. 0.05.
  --agent <id>           Fund only this agent. Can be repeated.
  --offset <n>           Skip first n matching agents.
  --limit <n>            Fund first n matching agents.
  --out <path>           Write plan/receipt JSON. Default arc/receipts/funding-<timestamp>.json.

Example:
  node arc/fund-agents.mjs --wallet-store colony/secrets/agent-wallets.local.json --amount 0.05
  node arc/fund-agents.mjs --broadcast --wallet-store colony/secrets/agent-wallets.local.json --amount 0.05 --limit 10
`);
}

function loadEnv(filePath) {
  if (!fs.existsSync(filePath)) return;
  for (const line of fs.readFileSync(filePath, "utf8").split("\n")) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#") || !trimmed.includes("=")) continue;
    const [key, ...rest] = trimmed.split("=");
    if (!process.env[key]) process.env[key] = rest.join("=").trim().replace(/^["']|["']$/g, "");
  }
}

function argValue(args, name, fallback = "") {
  const idx = args.indexOf(name);
  if (idx < 0) return fallback;
  return args[idx + 1] || fallback;
}

function argValues(args, name) {
  const values = [];
  for (let i = 0; i < args.length; i++) {
    if (args[i] === name && args[i + 1]) values.push(args[i + 1]);
  }
  return values;
}

function hasArg(args, name) {
  return args.includes(name);
}

function parseUsdc18(amount) {
  const [whole, fracRaw = ""] = String(amount).split(".");
  const frac = (fracRaw + "0".repeat(18)).slice(0, 18);
  return BigInt(whole || "0") * WEI_PER_USDC + BigInt(frac || "0");
}

function formatUsdc18(wei) {
  const value = BigInt(wei);
  const whole = value / WEI_PER_USDC;
  const frac = (value % WEI_PER_USDC).toString().padStart(18, "0").replace(/0+$/, "");
  return frac ? `${whole}.${frac}` : whole.toString();
}

function normalizePrivateKey(value) {
  let normalized = String(value || "").trim();
  if (!normalized) return "";
  if (normalized.includes("=")) normalized = normalized.split("=").pop().trim();
  normalized = normalized.replace(/^['"]|['"]$/g, "").trim();
  return normalized.startsWith("0x") ? normalized : `0x${normalized}`;
}

function readWallets(filePath) {
  const payload = JSON.parse(fs.readFileSync(filePath, "utf8"));
  const wallets = payload.wallets || {};
  return Object.entries(wallets)
    .map(([agentId, wallet]) => ({
      agent_id: agentId,
      address: wallet.address || "",
      provider: wallet.provider || payload.provider || "local",
    }))
    .filter((wallet) => wallet.address);
}

function buildPlan({ wallets, amountUsdc, selectedAgents, offset, limit }) {
  let selected = wallets;
  if (selectedAgents.length) {
    const wanted = new Set(selectedAgents);
    selected = selected.filter((wallet) => wanted.has(wallet.agent_id));
  }
  if (offset > 0) selected = selected.slice(offset);
  if (limit > 0) selected = selected.slice(0, limit);
  const amountWei = parseUsdc18(amountUsdc).toString();
  return selected.map((wallet) => ({
    transfer_id: `arc:fund:${wallet.agent_id}`,
    agent_id: wallet.agent_id,
    direction: "treasury_to_agent",
    from: TREASURY_ADDRESS,
    to: wallet.address,
    amount_usdc: Number(amountUsdc),
    amount_wei: amountWei,
    provider: wallet.provider,
  }));
}

async function broadcast(transfers) {
  const { createPublicClient, createWalletClient, http } = await import("viem");
  const { privateKeyToAccount } = await import("viem/accounts");
  const publicClient = createPublicClient({ chain: arc, transport: http(ARC_RPC_URL) });
  const chainId = await publicClient.getChainId();
  if (chainId !== ARC_CHAIN_ID) throw new Error(`Wrong chain id ${chainId}; expected ${ARC_CHAIN_ID}`);
  const key = normalizePrivateKey(process.env.ARC_TREASURY_PRIVATE_KEY || "");
  if (!key) throw new Error("ARC_TREASURY_PRIVATE_KEY is required for --broadcast");
  const treasury = privateKeyToAccount(key);
  const walletClient = createWalletClient({ account: treasury, chain: arc, transport: http(ARC_RPC_URL) });
  const receipts = [];
  for (let index = 0; index < transfers.length; index++) {
    const transfer = transfers[index];
    console.log(`[${index + 1}/${transfers.length}] ${transfer.agent_id} -> ${transfer.to} (${transfer.amount_usdc} USDC)`);
    const hash = await walletClient.sendTransaction({ to: transfer.to, value: BigInt(transfer.amount_wei) });
    console.log(`    tx: ${hash}`);
    const receipt = await publicClient.waitForTransactionReceipt({ hash });
    console.log(`    receipt: ${receipt.status} block=${receipt.blockNumber}`);
    receipts.push({
      ...transfer,
      tx_hash: hash,
      explorer_url: `${ARC_EXPLORER}/tx/${hash}`,
      status: receipt.status,
      block_number: receipt.blockNumber.toString(),
    });
  }
  return receipts;
}

async function main() {
  const args = process.argv.slice(2);
  if (hasArg(args, "--help") || hasArg(args, "-h")) {
    usage();
    return;
  }
  const walletStorePath = argValue(args, "--wallet-store");
  const amountUsdc = argValue(args, "--amount");
  if (!walletStorePath || !amountUsdc) {
    usage();
    process.exitCode = 2;
    return;
  }
  const amountWei = parseUsdc18(amountUsdc);
  if (amountWei <= 0n) throw new Error(`Invalid --amount: ${amountUsdc}`);
  const broadcastMode = hasArg(args, "--broadcast");
  const selectedAgents = argValues(args, "--agent");
  const offset = Number(argValue(args, "--offset", "0"));
  const limit = Number(argValue(args, "--limit", "0"));
  const outPath = argValue(
    args,
    "--out",
    path.join("arc", "receipts", `funding-${new Date().toISOString().replace(/[:.]/g, "-")}.json`),
  );

  const wallets = readWallets(walletStorePath);
  const transfers = buildPlan({ wallets, amountUsdc, selectedAgents, offset, limit });
  const payload = {
    schema_version: 1,
    mode: broadcastMode ? "broadcast" : "dry_run",
    chain: { name: "Arc Testnet", chain_id: ARC_CHAIN_ID, rpc_url: ARC_RPC_URL, native_token: "USDC", native_decimals: 18 },
    treasury_address: TREASURY_ADDRESS,
    wallet_store_path: walletStorePath,
    transfer_count: transfers.length,
    total_usdc: formatUsdc18(BigInt(transfers.length) * amountWei),
    transfers,
    receipts: [],
  };
  console.log(`${broadcastMode ? "Broadcasting" : "Dry-run"} funding for ${transfers.length} agent wallet(s).`);
  console.log(`Total: ${payload.total_usdc} Arc testnet USDC`);
  if (broadcastMode) payload.receipts = await broadcast(transfers);
  fs.mkdirSync(path.dirname(outPath), { recursive: true });
  fs.writeFileSync(outPath, JSON.stringify(payload, null, 2) + "\n");
  console.log(`Wrote ${broadcastMode ? "receipt" : "plan"}: ${outPath}`);
}

main().catch((err) => {
  console.error(err);
  process.exitCode = 1;
});
