#!/usr/bin/env node
// Operate the ColonyForecastMarket contract on Arc testnet.

import fs from "node:fs";
import path from "node:path";
import process from "node:process";
import {
  createPublicClient,
  createWalletClient,
  encodeFunctionData,
  formatUnits,
  http,
  keccak256,
  parseUnits,
  toHex,
} from "viem";
import { privateKeyToAccount } from "viem/accounts";
import {
  ARC_CHAIN_ID,
  ARC_EXPLORER,
  ARC_RPC_URL,
  loadEnv,
  normalizePrivateKey,
  parseArgs,
  readWalletStore,
  walletForAgent,
  writeJson,
} from "./x402-agent-common.mjs";

loadEnv();

const USDC = process.env.ARC_USDC_ADDRESS || "0x3600000000000000000000000000000000000000";
const DEFAULT_TREASURY = process.env.ARC_TREASURY_ADDRESS || "0xa569696dBf9191441D045891aADCf47a919cBC1c";
const ARTIFACT_PATH = path.join(
  "contracts",
  "out",
  "ColonyForecastMarket.sol",
  "ColonyForecastMarket.json",
);
const PACKAGED_ARTIFACT_PATH = path.join("arc", "forecast-market-artifact.json");

const arc = {
  id: ARC_CHAIN_ID,
  name: "Arc Testnet",
  nativeCurrency: { name: "USDC", symbol: "USDC", decimals: 18 },
  rpcUrls: { default: { http: [ARC_RPC_URL] } },
};

const erc20Abi = [
  {
    name: "approve",
    type: "function",
    stateMutability: "nonpayable",
    inputs: [{ name: "spender", type: "address" }, { name: "amount", type: "uint256" }],
    outputs: [{ type: "bool" }],
  },
  {
    name: "allowance",
    type: "function",
    stateMutability: "view",
    inputs: [{ name: "owner", type: "address" }, { name: "spender", type: "address" }],
    outputs: [{ type: "uint256" }],
  },
  {
    name: "balanceOf",
    type: "function",
    stateMutability: "view",
    inputs: [{ name: "account", type: "address" }],
    outputs: [{ type: "uint256" }],
  },
];

function usage() {
  console.log(`Usage:
  node arc/forecast-market.mjs <command> [options]

Commands:
  deploy                     Deploy ColonyForecastMarket.
  create-market              Create a market.
  stake                      Approve USDC and stake/vote from an ant wallet.
  settle                     Settle a market result.
  claim                      Claim winnings/refund for an ant.
  withdraw-treasury          Withdraw market treasury fee.
  totals                     Show market totals.
  market-id                  Print deterministic bytes32 market id.

Common options:
  --contract <address>       Forecast market contract. Defaults FORECAST_MARKET_ADDRESS.
  --wallet-store <path>      Agent wallet store for ant-signed commands.
  --agent <id>               Ant id for stake/claim.
  --market-id <bytes32>      Market id. Use 0x... or --market-key.
  --market-key <string>      Deterministic id source, hashed with keccak256.
  --out <path>               Receipt output JSON.

deploy:
  --treasury <address>       Treasury address. Default ARC_TREASURY_ADDRESS.

create-market:
  --market-type three_way|binary
  --close-time <unix>        0 means no close time.
  --fee-bps <n>              Treasury fee on losing pool. Default 1000.
  --metadata-uri <uri>

stake:
  --outcome home|draw|away
  --amount <USDC>

settle:
  --result home|draw|away

Examples:
  node arc/forecast-market.mjs deploy
  node arc/forecast-market.mjs market-id --market-key 'worldcup:2026:brazil-morocco'
  node arc/forecast-market.mjs create-market --contract 0x... --market-key 'worldcup:2026:brazil-morocco' --market-type three_way
  node arc/forecast-market.mjs stake --contract 0x... --wallet-store colony/secrets/agent-wallets.local.json --agent ant_0001 --market-key 'worldcup:2026:brazil-morocco' --outcome home --amount 0.001
`);
}

const args = parseArgs();
const command = args._[0] || "";
if (!command || args.help || args.h) {
  usage();
  process.exit(args.help || args.h ? 0 : 2);
}

const artifact = readArtifact();
const publicClient = createPublicClient({ chain: arc, transport: http(ARC_RPC_URL) });

if (command === "deploy") {
  await deploy();
} else if (command === "market-id") {
  console.log(resolveMarketId());
} else if (command === "create-market") {
  await createMarket();
} else if (command === "stake") {
  await stake();
} else if (command === "settle") {
  await settle();
} else if (command === "claim") {
  await claim(false);
} else if (command === "claim-refund") {
  await claim(true);
} else if (command === "withdraw-treasury") {
  await withdrawTreasury();
} else if (command === "totals") {
  await totals();
} else {
  usage();
  throw new Error(`Unknown command: ${command}`);
}

async function deploy() {
  const account = treasuryAccount();
  const walletClient = createWalletClient({ account, chain: arc, transport: http(ARC_RPC_URL) });
  const treasury = String(args.treasury || DEFAULT_TREASURY);
  console.log(`Deploying ColonyForecastMarket with owner=${account.address}, treasury=${treasury}`);
  const hash = await walletClient.deployContract({
    abi: artifact.abi,
    bytecode: artifact.bytecode.object || artifact.bytecode,
    args: [USDC, treasury],
  });
  console.log(`deploy tx: ${hash}`);
  const receipt = await publicClient.waitForTransactionReceipt({ hash });
  const payload = receiptPayload("deploy", {
    tx_hash: hash,
    status: receipt.status,
    block_number: receipt.blockNumber.toString(),
    contract_address: receipt.contractAddress,
    explorer_url: `${ARC_EXPLORER}/tx/${hash}`,
    usdc: USDC,
    treasury,
  });
  writeReceipt(payload);
  console.log(`contract: ${receipt.contractAddress}`);
}

async function createMarket() {
  const contract = contractAddress();
  const account = treasuryAccount();
  const marketId = resolveMarketId();
  const marketType = marketTypeValue(args.marketType || "three_way");
  const closeTime = BigInt(args.closeTime || "0");
  const feeBps = Number(args.feeBps || "1000");
  const metadataURI = String(args.metadataUri || "");
  const hash = await writeContract(account, contract, "createMarket", [
    marketId,
    marketType,
    closeTime,
    feeBps,
    metadataURI,
  ]);
  const receipt = await publicClient.waitForTransactionReceipt({ hash });
  writeReceipt(receiptPayload("create-market", {
    tx_hash: hash,
    status: receipt.status,
    block_number: receipt.blockNumber.toString(),
    contract,
    market_id: marketId,
    market_type: args.marketType || "three_way",
    close_time: closeTime.toString(),
    fee_bps: feeBps,
    metadata_uri: metadataURI,
  }));
  console.log(`created market ${marketId}: ${hash}`);
}

async function stake() {
  const contract = contractAddress();
  const wallet = agentWallet();
  const account = privateKeyToAccount(normalizePrivateKey(wallet.privateKey));
  const marketId = resolveMarketId();
  const outcome = outcomeValue(args.outcome);
  const amount = parseUsdc6(args.amount);

  const allowance = await publicClient.readContract({
    address: USDC,
    abi: erc20Abi,
    functionName: "allowance",
    args: [account.address, contract],
  });
  const walletClient = createWalletClient({ account, chain: arc, transport: http(ARC_RPC_URL) });
  const hashes = [];
  if (allowance < amount) {
    console.log(`approving ${formatUsdc6(amount)} USDC for market contract`);
    const approveHash = await walletClient.writeContract({
      address: USDC,
      abi: erc20Abi,
      functionName: "approve",
      args: [contract, amount],
    });
    await publicClient.waitForTransactionReceipt({ hash: approveHash });
    hashes.push({ type: "approve", tx_hash: approveHash, explorer_url: `${ARC_EXPLORER}/tx/${approveHash}` });
  }

  const stakeHash = await writeContract(account, contract, "stake", [marketId, outcome, amount]);
  const receipt = await publicClient.waitForTransactionReceipt({ hash: stakeHash });
  hashes.push({ type: "stake", tx_hash: stakeHash, explorer_url: `${ARC_EXPLORER}/tx/${stakeHash}` });
  writeReceipt(receiptPayload("stake", {
    status: receipt.status,
    block_number: receipt.blockNumber.toString(),
    contract,
    market_id: marketId,
    agent_id: wallet.agentId,
    wallet: account.address,
    outcome: args.outcome,
    amount_usdc: formatUsdc6(amount),
    transactions: hashes,
  }));
  console.log(`staked ${formatUsdc6(amount)} USDC on ${args.outcome}: ${stakeHash}`);
}

async function settle() {
  const contract = contractAddress();
  const account = treasuryAccount();
  const marketId = resolveMarketId();
  const result = outcomeValue(args.result);
  const hash = await writeContract(account, contract, "settle", [marketId, result]);
  const receipt = await publicClient.waitForTransactionReceipt({ hash });
  writeReceipt(receiptPayload("settle", {
    tx_hash: hash,
    status: receipt.status,
    block_number: receipt.blockNumber.toString(),
    contract,
    market_id: marketId,
    result: args.result,
  }));
  console.log(`settled ${marketId} as ${args.result}: ${hash}`);
}

async function claim(refund) {
  const contract = contractAddress();
  const wallet = agentWallet();
  const account = privateKeyToAccount(normalizePrivateKey(wallet.privateKey));
  const marketId = resolveMarketId();
  const fn = refund ? "claimRefund" : "claim";
  const hash = await writeContract(account, contract, fn, [marketId]);
  const receipt = await publicClient.waitForTransactionReceipt({ hash });
  writeReceipt(receiptPayload(fn, {
    tx_hash: hash,
    status: receipt.status,
    block_number: receipt.blockNumber.toString(),
    contract,
    market_id: marketId,
    agent_id: wallet.agentId,
    wallet: account.address,
  }));
  console.log(`${fn} ${marketId}: ${hash}`);
}

async function withdrawTreasury() {
  const contract = contractAddress();
  const account = treasuryAccount();
  const marketId = resolveMarketId();
  const hash = await writeContract(account, contract, "withdrawTreasury", [marketId]);
  const receipt = await publicClient.waitForTransactionReceipt({ hash });
  writeReceipt(receiptPayload("withdraw-treasury", {
    tx_hash: hash,
    status: receipt.status,
    block_number: receipt.blockNumber.toString(),
    contract,
    market_id: marketId,
  }));
  console.log(`withdrew treasury fee for ${marketId}: ${hash}`);
}

async function totals() {
  const contract = contractAddress();
  const marketId = resolveMarketId();
  const result = await publicClient.readContract({
    address: contract,
    abi: artifact.abi,
    functionName: "marketTotals",
    args: [marketId],
  });
  const payload = {
    market_id: marketId,
    home_usdc: formatUsdc6(result[0]),
    draw_usdc: formatUsdc6(result[1]),
    away_usdc: formatUsdc6(result[2]),
    total_usdc: formatUsdc6(result[3]),
  };
  console.log(JSON.stringify(payload, null, 2));
}

async function writeContract(account, address, functionName, args_) {
  const walletClient = createWalletClient({ account, chain: arc, transport: http(ARC_RPC_URL) });
  return walletClient.writeContract({
    address,
    abi: artifact.abi,
    functionName,
    args: args_,
  });
}

function readArtifact() {
  const artifactPath = fs.existsSync(ARTIFACT_PATH) ? ARTIFACT_PATH : PACKAGED_ARTIFACT_PATH;
  if (!fs.existsSync(artifactPath)) {
    throw new Error(`Missing ${ARTIFACT_PATH} and ${PACKAGED_ARTIFACT_PATH}; run: forge build`);
  }
  return JSON.parse(fs.readFileSync(artifactPath, "utf8"));
}

function treasuryAccount() {
  const key = normalizePrivateKey(process.env.ARC_TREASURY_PRIVATE_KEY || "");
  if (!key) throw new Error("ARC_TREASURY_PRIVATE_KEY is required");
  return privateKeyToAccount(key);
}

function agentWallet() {
  const store = readWalletStore(String(args.walletStore || ""));
  const wallet = walletForAgent(store, String(args.agent || ""));
  if (!wallet.privateKey) throw new Error(`Agent ${wallet.agentId} has no local private key`);
  return wallet;
}

function contractAddress() {
  const value = String(args.contract || process.env.FORECAST_MARKET_ADDRESS || "");
  if (!/^0x[0-9a-fA-F]{40}$/.test(value)) {
    throw new Error("--contract or FORECAST_MARKET_ADDRESS is required");
  }
  return value;
}

function resolveMarketId() {
  if (args.marketId) {
    const id = String(args.marketId);
    if (!/^0x[0-9a-fA-F]{64}$/.test(id)) throw new Error(`Invalid --market-id: ${id}`);
    return id;
  }
  if (!args.marketKey) throw new Error("--market-id or --market-key is required");
  return keccak256(toHex(String(args.marketKey)));
}

function marketTypeValue(value) {
  if (value === "three_way" || value === "group") return 0;
  if (value === "binary" || value === "knockout") return 1;
  throw new Error("--market-type must be three_way or binary");
}

function outcomeValue(value) {
  if (value === "home" || value === "home_win" || value === "home_qualifies") return 0;
  if (value === "draw") return 1;
  if (value === "away" || value === "away_win" || value === "away_qualifies") return 2;
  throw new Error("--outcome/--result must be home, draw, or away");
}

function parseUsdc6(value) {
  if (!value) throw new Error("--amount is required");
  return parseUnits(String(value), 6);
}

function formatUsdc6(value) {
  return formatUnits(BigInt(value), 6);
}

function receiptPayload(action, payload) {
  return {
    schema_version: 1,
    action,
    chain: {
      name: "Arc Testnet",
      chain_id: ARC_CHAIN_ID,
      rpc_url: ARC_RPC_URL,
      usdc: USDC,
      explorer: ARC_EXPLORER,
    },
    created_at: new Date().toISOString(),
    ...payload,
  };
}

function writeReceipt(payload) {
  const outPath = String(
    args.out
      || path.join("arc", "receipts", `forecast-${payload.action}-${new Date().toISOString().replace(/[:.]/g, "-")}.json`),
  );
  writeJson(outPath, payload);
  console.log(`wrote receipt: ${outPath}`);
}
