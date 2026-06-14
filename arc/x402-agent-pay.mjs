#!/usr/bin/env node
// Real x402 buyer client for ant-to-ant payments through Circle Gateway.

import path from "node:path";
import process from "node:process";
import { GatewayClient } from "@circle-fin/x402-batching/client";
import {
  ARC_CHAIN_NAME,
  ARC_RPC_URL,
  DEFAULT_RECEIPTS_PATH,
  endpointForService,
  loadEnv,
  normalizeAddress,
  normalizePrivateKey,
  parseArgs,
  readWalletStore,
  serviceForName,
  usageServices,
  walletForAgent,
  writeJson,
} from "./x402-agent-common.mjs";

loadEnv();

function usage() {
  console.log(`Usage:
  node arc/x402-agent-pay.mjs --wallet-store <agent-wallets.json> --buyer <agent_id> --seller <agent_id> --service <name> [options]

Options:
  --base-url <url>        x402 ant service base URL. Default http://localhost:4020.
  --body-json <json>      Extra JSON body merged into the paid request.
  --deposit <USDC>        Deposit buyer USDC into Circle Gateway before paying.
  --check-supports        Optional GET probe; POST ant routes can still pay if this is inconclusive.
  --out <path>            Write payment result JSON. Default arc/receipts/x402-pay-<timestamp>.json.

Services:
${usageServices()}

Example:
  node arc/x402-agent-pay.mjs --wallet-store colony/secrets/agent-wallets.local.json --buyer ant_0001 --seller ant_0002 --service summary --deposit 0.005
`);
}

const args = parseArgs();
if (args.help || args.h) {
  usage();
  process.exit(0);
}

const walletStorePath = args.walletStore;
const buyerId = String(args.buyer || "");
const sellerId = String(args.seller || "");
const serviceName = String(args.service || "");
if (!walletStorePath || !buyerId || !sellerId || !serviceName) {
  usage();
  process.exit(2);
}

const store = readWalletStore(walletStorePath);
const buyer = walletForAgent(store, buyerId, "buyer");
walletForAgent(store, sellerId, "seller");
const service = serviceForName(serviceName);
const privateKey = normalizePrivateKey(buyer.privateKey || process.env.X402_BUYER_PRIVATE_KEY || "");
if (!privateKey) {
  throw new Error(
    `Buyer ${buyerId} has no local private key. Circle GatewayClient needs an EOA signer; `
      + "use a local wallet store or wire a Dynamic MPC BatchEvmSigner.",
  );
}

const client = new GatewayClient({
  chain: ARC_CHAIN_NAME,
  privateKey,
  rpcUrl: process.env.ARC_RPC_URL || ARC_RPC_URL,
});

if (normalizeAddress(client.address) !== normalizeAddress(buyer.address)) {
  throw new Error(`Buyer private key resolves to ${client.address}, but ${buyerId} is ${buyer.address}`);
}

const baseUrl = String(args.baseUrl || process.env.X402_AGENT_SERVICE_URL || "http://localhost:4020");
const url = endpointForService(baseUrl, serviceName, sellerId);
const extraBody = args.bodyJson ? JSON.parse(String(args.bodyJson)) : {};
const body = {
  buyer_id: buyerId,
  seller_id: sellerId,
  service: serviceName,
  round_id: args.roundId || "x402_agent_market",
  resource_id: args.resourceId || `${serviceName}:${sellerId}`,
  ...extraBody,
};

console.log(`Buyer ${buyerId} (${buyer.address})`);
console.log(`Seller ${sellerId}`);
console.log(`Service ${serviceName}: ${service.price} USDC`);

if (args.deposit) {
  console.log(`Depositing ${args.deposit} USDC into Circle Gateway for ${buyerId}...`);
  const deposit = await client.deposit(String(args.deposit));
  console.log(`Deposit tx: ${deposit.depositTxHash}`);
}

if (args.checkSupports) {
  const support = await client.supports(url);
  console.log(`Gateway support: ${support.supported ? "yes" : "no"}`);
  if (!support.supported) {
    console.warn(`Gateway support probe was inconclusive: ${support.error || "not supported by GET probe"}`);
  }
}

const result = await client.pay(url, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

const payload = {
  schema_version: 1,
  rail: "x402_circle_gateway",
  status: result.status,
  buyer_id: buyerId,
  buyer_wallet: buyer.address,
  seller_id: sellerId,
  service_name: serviceName,
  requested_price_usdc: service.price,
  paid_amount_usdc: result.formattedAmount,
  transaction: result.transaction,
  response: result.data,
};

const outPath = String(
  args.out
    || path.join("arc", "receipts", `x402-pay-${new Date().toISOString().replace(/[:.]/g, "-")}.json`),
);
writeJson(outPath, payload);
console.log(`Paid ${result.formattedAmount} USDC via x402; status=${result.status}; tx=${result.transaction}`);
console.log(`Wrote payment result: ${outPath}`);
