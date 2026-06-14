#!/usr/bin/env node
// Query Circle Gateway transfer status for a real x402 payment UUID.

import process from "node:process";
import { GatewayClient } from "@circle-fin/x402-batching/client";
import {
  ARC_CHAIN_NAME,
  ARC_RPC_URL,
  loadEnv,
  normalizePrivateKey,
  parseArgs,
  readWalletStore,
  walletForAgent,
} from "./x402-agent-common.mjs";

loadEnv();

function usage() {
  console.log(`Usage:
  node arc/x402-transfer-status.mjs --wallet-store <agent-wallets.json> --agent <agent_id> --transfer <uuid>

The agent is only used as the Circle Gateway API signer for the query.
It must be a local EOA wallet with a private key.
`);
}

const args = parseArgs();
if (args.help || args.h) {
  usage();
  process.exit(0);
}

const walletStorePath = args.walletStore;
const agentId = String(args.agent || "");
const transferId = String(args.transfer || "");
if (!walletStorePath || !agentId || !transferId) {
  usage();
  process.exit(2);
}

const store = readWalletStore(walletStorePath);
const wallet = walletForAgent(store, agentId);
const privateKey = normalizePrivateKey(wallet.privateKey || process.env.X402_BUYER_PRIVATE_KEY || "");
if (!privateKey) {
  throw new Error(`Agent ${agentId} has no local private key; Gateway transfer queries need an EOA signer.`);
}

const client = new GatewayClient({
  chain: ARC_CHAIN_NAME,
  privateKey,
  rpcUrl: process.env.ARC_RPC_URL || ARC_RPC_URL,
});

const transfer = await client.getTransferById(transferId);
console.log(JSON.stringify(transfer, null, 2));
