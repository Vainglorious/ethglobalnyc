#!/usr/bin/env node
// Convert Colony internal economy events into Arc testnet USDC transfers.
//
// Default mode is DRY RUN. Use --broadcast to send native USDC transactions on
// Arc testnet. This script nets balance_update events per agent so tiny internal
// payments become one settlement transfer per wallet.

import fs from "node:fs";
import path from "node:path";
import process from "node:process";

loadEnv(path.resolve("arc/.env"));

const ARC_CHAIN_ID = 5042002;
const ARC_RPC_URL = process.env.ARC_RPC_URL || "https://rpc.testnet.arc.network";
const ARC_EXPLORER = "https://testnet.arcscan.app";
const DEFAULT_SCALE = Number(process.env.ARC_LEDGER_SCALE || "0.001");
const TREASURY_ADDRESS = (process.env.ARC_TREASURY_ADDRESS || "0x1be3F1edA4C654BdF3bDcF973EF861346EA52D8F").trim();

const arc = {
  id: ARC_CHAIN_ID,
  name: "Arc Testnet",
  nativeCurrency: { name: "USDC", symbol: "USDC", decimals: 18 },
  rpcUrls: { default: { http: [ARC_RPC_URL] } },
};

const WEI_PER_USDC = 10n ** 18n;

function loadEnv(filePath) {
  if (!fs.existsSync(filePath)) return;
  for (const line of fs.readFileSync(filePath, "utf8").split("\n")) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#") || !trimmed.includes("=")) continue;
    const [key, ...rest] = trimmed.split("=");
    if (!process.env[key]) process.env[key] = rest.join("=").trim().replace(/^["']|["']$/g, "");
  }
}

function usage() {
  console.log(`Usage:
  node arc/ledger-to-transfers.mjs --events <events.jsonl> --wallet-store <agent-wallets.json> [options]

Options:
  --broadcast              Send transactions. Omitted = dry-run only.
  --events <path>          Colony JSONL events path.
  --wallet-store <path>    Colony wallet store with agent addresses/private keys.
  --scale <number>         Testnet amount multiplier. Default ${DEFAULT_SCALE}.
  --credits-only           Only treasury -> agent transfers; skip agent -> treasury debits.
  --out <path>             Write plan/receipt JSON. Default arc/receipts/<timestamp>.json.

Examples:
  node arc/ledger-to-transfers.mjs --events colony/runs/api/<id>/events.jsonl --wallet-store colony/secrets/agent-wallets.local.json
  node arc/ledger-to-transfers.mjs --broadcast --events /tmp/events.jsonl --wallet-store colony/secrets/agent-wallets.local.json --scale 0.001
`);
}

function argValue(args, name, fallback = "") {
  const idx = args.indexOf(name);
  if (idx < 0) return fallback;
  return args[idx + 1] || fallback;
}

function hasArg(args, name) {
  return args.includes(name);
}

function readJsonl(filePath) {
  return fs.readFileSync(filePath, "utf8")
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => JSON.parse(line));
}

function readWallets(filePath) {
  if (!filePath) return new Map();
  const payload = JSON.parse(fs.readFileSync(filePath, "utf8"));
  const wallets = payload.wallets || {};
  const byAgent = new Map();
  for (const [agentId, wallet] of Object.entries(wallets)) {
    byAgent.set(agentId, {
      agentId,
      address: wallet.address || "",
      privateKey: wallet.private_key || "",
      provider: wallet.provider || payload.provider || "local",
    });
  }
  return byAgent;
}

function normalizePrivateKey(value) {
  if (!value) return "";
  return value.startsWith("0x") ? value : `0x${value}`;
}

function amountFromSim(simAmount, scale) {
  const value = Math.abs(Number(simAmount || 0)) * scale;
  return Math.round(value * 1_000_000) / 1_000_000;
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

function transferId(agentId, direction) {
  return `arc:${direction}:${agentId}`;
}

function buildPlan({ events, wallets, scale, creditsOnly }) {
  const netByAgent = new Map();
  const reasonsByAgent = new Map();
  for (const event of events) {
    if (event.event_type !== "balance_update") continue;
    if (!event.agent_id || event.agent_id === "colony_treasury") continue;
    const delta = Number(event.delta || 0);
    netByAgent.set(event.agent_id, (netByAgent.get(event.agent_id) || 0) + delta);
    if (!reasonsByAgent.has(event.agent_id)) reasonsByAgent.set(event.agent_id, new Set());
    reasonsByAgent.get(event.agent_id).add(event.reason || "balance_update");
  }

  const transfers = [];
  const skipped = [];
  for (const [agentId, netSimDeltaRaw] of [...netByAgent.entries()].sort()) {
    const netSimDelta = Math.round(netSimDeltaRaw * 10_000) / 10_000;
    if (Math.abs(netSimDelta) < 0.0001) continue;
    const amountUsdc = amountFromSim(netSimDelta, scale);
    if (amountUsdc <= 0) continue;
    const wallet = wallets.get(agentId);
    if (!wallet || !wallet.address) {
      skipped.push({ agent_id: agentId, reason: "missing_wallet_address", net_sim_delta: netSimDelta, amount_usdc: amountUsdc });
      continue;
    }
    const direction = netSimDelta > 0 ? "treasury_to_agent" : "agent_to_treasury";
    if (direction === "agent_to_treasury" && creditsOnly) {
      skipped.push({ agent_id: agentId, reason: "credits_only_skip_debit", net_sim_delta: netSimDelta, amount_usdc: amountUsdc });
      continue;
    }
    if (direction === "agent_to_treasury" && !wallet.privateKey) {
      skipped.push({ agent_id: agentId, reason: "missing_agent_private_key", provider: wallet.provider, net_sim_delta: netSimDelta, amount_usdc: amountUsdc });
      continue;
    }
    transfers.push({
      transfer_id: transferId(agentId, direction),
      agent_id: agentId,
      direction,
      from: direction === "treasury_to_agent" ? TREASURY_ADDRESS : wallet.address,
      to: direction === "treasury_to_agent" ? wallet.address : TREASURY_ADDRESS,
      amount_usdc: amountUsdc,
      amount_wei: parseUsdc18(amountUsdc).toString(),
      net_sim_delta: netSimDelta,
      reasons: [...(reasonsByAgent.get(agentId) || [])].sort(),
      provider: wallet.provider,
    });
  }
  return { transfers, skipped };
}

async function broadcastPlan(plan, wallets) {
  const { createPublicClient, createWalletClient, http } = await import("viem");
  const { privateKeyToAccount } = await import("viem/accounts");
  const publicClient = createPublicClient({ chain: arc, transport: http(ARC_RPC_URL) });
  const chainId = await publicClient.getChainId();
  if (chainId !== ARC_CHAIN_ID) {
    throw new Error(`Wrong chain id ${chainId}; expected Arc testnet ${ARC_CHAIN_ID}`);
  }

  const treasuryKey = normalizePrivateKey(process.env.ARC_TREASURY_PRIVATE_KEY || "");
  if (!treasuryKey) throw new Error("ARC_TREASURY_PRIVATE_KEY is required for --broadcast");

  const treasury = privateKeyToAccount(treasuryKey);
  if (treasury.address.toLowerCase() !== TREASURY_ADDRESS.toLowerCase()) {
    console.warn(`Warning: ARC_TREASURY_ADDRESS=${TREASURY_ADDRESS} but key resolves to ${treasury.address}`);
  }
  const treasuryClient = createWalletClient({ account: treasury, chain: arc, transport: http(ARC_RPC_URL) });
  const clients = new Map([["treasury", treasuryClient]]);
  const receipts = [];

  for (const transfer of plan.transfers) {
    let client = treasuryClient;
    if (transfer.direction === "agent_to_treasury") {
      const wallet = wallets.get(transfer.agent_id);
      const privateKey = normalizePrivateKey(wallet?.privateKey || "");
      if (!privateKey) {
        receipts.push({ ...transfer, status: "skipped", reason: "missing_agent_private_key" });
        continue;
      }
      if (!clients.has(transfer.agent_id)) {
        const account = privateKeyToAccount(privateKey);
        clients.set(transfer.agent_id, createWalletClient({ account, chain: arc, transport: http(ARC_RPC_URL) }));
      }
      client = clients.get(transfer.agent_id);
    }
    const hash = await client.sendTransaction({
      to: transfer.to,
      value: BigInt(transfer.amount_wei),
    });
    const receipt = await publicClient.waitForTransactionReceipt({ hash });
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
  const eventsPath = argValue(args, "--events");
  const walletStorePath = argValue(args, "--wallet-store");
  if (!eventsPath || !walletStorePath) {
    usage();
    process.exitCode = 2;
    return;
  }
  const broadcast = hasArg(args, "--broadcast");
  const scale = Number(argValue(args, "--scale", String(DEFAULT_SCALE)));
  const creditsOnly = hasArg(args, "--credits-only");
  const outPath = argValue(
    args,
    "--out",
    path.join("arc", "receipts", `${new Date().toISOString().replace(/[:.]/g, "-")}.json`),
  );
  if (!Number.isFinite(scale) || scale <= 0) throw new Error(`Invalid --scale: ${scale}`);

  const events = readJsonl(eventsPath);
  const wallets = readWallets(walletStorePath);
  const plan = buildPlan({ events, wallets, scale, creditsOnly });
  const payload = {
    schema_version: 1,
    mode: broadcast ? "broadcast" : "dry_run",
    chain: {
      name: "Arc Testnet",
      chain_id: ARC_CHAIN_ID,
      rpc_url: ARC_RPC_URL,
      native_token: "USDC",
      native_decimals: 18,
      explorer: ARC_EXPLORER,
    },
    treasury_address: TREASURY_ADDRESS,
    scale,
    events_path: eventsPath,
    wallet_store_path: walletStorePath,
    transfer_count: plan.transfers.length,
    skipped_count: plan.skipped.length,
    transfers: plan.transfers,
    skipped: plan.skipped,
    receipts: [],
  };

  console.log(`${broadcast ? "Broadcasting" : "Dry-run"} ${plan.transfers.length} Arc transfer(s); skipped ${plan.skipped.length}.`);
  if (broadcast) {
    payload.receipts = await broadcastPlan(plan, wallets);
  }
  fs.mkdirSync(path.dirname(outPath), { recursive: true });
  fs.writeFileSync(outPath, JSON.stringify(payload, null, 2) + "\n");
  console.log(`Wrote ${broadcast ? "receipt" : "plan"}: ${outPath}`);
  if (!broadcast) {
    const totalOut = plan.transfers
      .filter((transfer) => transfer.direction === "treasury_to_agent")
      .reduce((sum, transfer) => sum + Number(transfer.amount_usdc), 0);
    const totalIn = plan.transfers
      .filter((transfer) => transfer.direction === "agent_to_treasury")
      .reduce((sum, transfer) => sum + Number(transfer.amount_usdc), 0);
    console.log(`Treasury out: ${formatUsdc18(parseUsdc18(totalOut))} USDC`);
    console.log(`Treasury in : ${formatUsdc18(parseUsdc18(totalIn))} USDC`);
    console.log("Add --broadcast to send these transactions on Arc testnet.");
  }
}

main().catch((err) => {
  console.error(err);
  process.exitCode = 1;
});
