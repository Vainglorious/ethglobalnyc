#!/usr/bin/env node
// Deposit local ant USDC into Circle Gateway so it can pay x402 resources.

import process from "node:process";
import { GatewayClient } from "@circle-fin/x402-batching/client";
import {
  ARC_CHAIN_NAME,
  ARC_RPC_URL,
  loadEnv,
  normalizeAddress,
  normalizePrivateKey,
  parseArgs,
  readWalletStore,
  walletForAgent,
} from "./x402-agent-common.mjs";

loadEnv();

function usage() {
  console.log(`Usage:
  node arc/x402-gateway-deposit.mjs --wallet-store <agent-wallets.json> --agent <agent_id> [options]

Options:
  --amount <USDC>       Deposit this amount into Gateway.
  --balances            Print wallet and Gateway balances.

Example:
  node arc/x402-gateway-deposit.mjs --wallet-store colony/secrets/agent-wallets.local.json --agent ant_0001 --amount 0.005 --balances
`);
}

const args = parseArgs();
if (args.help || args.h) {
  usage();
  process.exit(0);
}

const walletStorePath = args.walletStore;
const agentId = String(args.agent || "");
if (!walletStorePath || !agentId) {
  usage();
  process.exit(2);
}

const store = readWalletStore(walletStorePath);
const wallet = walletForAgent(store, agentId);
const privateKey = normalizePrivateKey(wallet.privateKey || process.env.X402_BUYER_PRIVATE_KEY || "");
if (!privateKey) {
  throw new Error(`Agent ${agentId} has no local private key; Circle GatewayClient deposit requires an EOA signer.`);
}

const client = new GatewayClient({
  chain: ARC_CHAIN_NAME,
  privateKey,
  rpcUrl: process.env.ARC_RPC_URL || ARC_RPC_URL,
});

if (normalizeAddress(client.address) !== normalizeAddress(wallet.address)) {
  throw new Error(`Private key resolves to ${client.address}, but ${agentId} is ${wallet.address}`);
}

console.log(`Agent ${agentId}: ${wallet.address}`);

if (args.balances) {
  await printBalances(client, "before");
}

if (args.amount) {
  const deposit = await client.deposit(String(args.amount));
  console.log(`Deposited ${deposit.formattedAmount} USDC`);
  if (deposit.approvalTxHash) console.log(`Approval tx: ${deposit.approvalTxHash}`);
  console.log(`Deposit tx: ${deposit.depositTxHash}`);
}

if (args.balances) {
  await printBalances(client, "after");
}

async function printBalances(client, label) {
  const balances = await client.getBalances();
  console.log(`${label} wallet USDC : ${balances.wallet.formatted}`);
  console.log(`${label} gateway USDC: ${balances.gateway.formattedAvailable} available / ${balances.gateway.formattedTotal} total`);
}
