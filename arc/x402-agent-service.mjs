#!/usr/bin/env node
// Real x402 seller service for ant-to-ant payments on Arc testnet.
//
// Each protected endpoint resolves the seller ant from the wallet store and
// configures Circle Gateway with that ant wallet as payTo. The resulting
// receipt is a real Gateway x402 payment, not a simulated ledger entry.

import express from "express";
import { createGatewayMiddleware } from "@circle-fin/x402-batching/server";
import {
  ARC_NETWORK,
  CIRCLE_FACILITATOR_URL,
  DEFAULT_RECEIPTS_PATH,
  SERVICES,
  appendJsonl,
  buildReceipt,
  loadEnv,
  parseArgs,
  readWalletStore,
  sameLineage,
  serviceForName,
  serviceNameForFindingAccess,
  usageServices,
  walletForAgent,
  x402Price,
} from "./x402-agent-common.mjs";

loadEnv();

function usage() {
  console.log(`Usage:
  node arc/x402-agent-service.mjs --wallet-store <agent-wallets.json> [options]

Options:
  --wallet-store <path>   Wallet store used to resolve buyer/seller ant addresses.
  --port <number>         Port to listen on. Default 4020.
  --host <host>           Host to bind. Default 127.0.0.1.
  --receipts <path>       JSONL receipt sink. Default ${DEFAULT_RECEIPTS_PATH}.

Services:
${usageServices()}

Example:
  node arc/x402-agent-service.mjs --wallet-store colony/secrets/agent-wallets.local.json --port 4020
`);
}

const args = parseArgs();
if (args.help || args.h) {
  usage();
  process.exit(0);
}

const walletStorePath = args.walletStore;
if (!walletStorePath) {
  usage();
  process.exit(2);
}

const port = Number(args.port || process.env.X402_AGENT_SERVICE_PORT || "4020");
const host = String(args.host || process.env.X402_AGENT_SERVICE_HOST || "127.0.0.1");
const receiptsPath = String(args.receipts || process.env.X402_AGENT_RECEIPTS || DEFAULT_RECEIPTS_PATH);
const store = readWalletStore(walletStorePath);
const app = express();
const gateways = new Map();

app.use(express.json({ limit: "256kb" }));

app.get("/health", (_req, res) => {
  res.json({
    ok: true,
    rail: "x402_circle_gateway",
    network: ARC_NETWORK,
    wallet_store: walletStorePath,
    seller_mode: "agent_wallet",
    services: publicServices(),
  });
});

app.get("/offers", (req, res) => {
  const sellerId = String(req.query.seller_id || "");
  const offers = [...store.wallets]
    .filter((wallet) => !sellerId || wallet.agentId === sellerId)
    .map((wallet) => ({
      seller_id: wallet.agentId,
      seller_wallet: wallet.address,
      provider: wallet.provider,
      services: publicServices(),
    }));
  res.json({ network: ARC_NETWORK, seller_mode: "agent_wallet", offers });
});

app.post(
  "/ants/:sellerId/summary",
  preflightPolicy("summary"),
  requirePayment("summary"),
  paidHandler("summary", makeSummary),
);

app.post(
  "/ants/:sellerId/audit",
  preflightPolicy("audit"),
  requirePayment("audit"),
  paidHandler("audit", makeAudit),
);

app.post(
  "/scouts/:sellerId/findings/:accessLevel",
  (req, res, next) => {
    try {
      req.serviceName = serviceNameForFindingAccess(req.params.accessLevel);
      next();
    } catch (err) {
      res.status(400).json({ error: err.message });
    }
  },
  preflightPolicy(),
  requirePayment(),
  paidHandler(undefined, makeFinding),
);

app.use((err, _req, res, _next) => {
  console.error(err);
  res.status(500).json({ error: err.message || "x402 service error" });
});

const server = app.listen(port, host, () => {
  console.log(`x402 ant service listening at http://${host}:${port}`);
  console.log(`Network: ${ARC_NETWORK}`);
  console.log(`Seller mode: agent wallet payTo`);
  console.log(`Receipts: ${receiptsPath}`);
});

server.on("error", (err) => {
  console.error(`Failed to start x402 ant service on ${host}:${port}: ${err.message}`);
  process.exitCode = 1;
});

function requirePayment(staticServiceName) {
  return (req, res, next) => {
    const serviceName = staticServiceName || req.serviceName;
    let seller;
    try {
      serviceForName(serviceName);
      seller = walletForAgent(store, req.params.sellerId, "seller");
    } catch (err) {
      res.status(404).json({ error: err.message });
      return;
    }

    const gateway = gatewayForSeller(seller);
    return gateway.require(x402Price(serviceName))(req, res, next);
  };
}

function preflightPolicy(staticServiceName) {
  return (req, res, next) => {
    const serviceName = staticServiceName || req.serviceName;
    try {
      serviceForName(serviceName);
      const seller = walletForAgent(store, req.params.sellerId, "seller");
      const buyerId = String(req.body?.buyer_id || req.body?.buyerId || "");
      if (!buyerId) {
        res.status(400).json({ error: "buyer_id is required before payment so bad requests do not get charged" });
        return;
      }
      const buyer = walletForAgent(store, buyerId, "buyer");
      if (buyer.agentId === seller.agentId) {
        res.status(409).json({ error: "self-payment is not allowed" });
        return;
      }
      if (sameLineage(buyer, seller)) {
        res.status(409).json({ error: "same-lineage ant payments are not allowed" });
        return;
      }
      req.claimedBuyer = buyer;
      req.seller = seller;
      next();
    } catch (err) {
      res.status(404).json({ error: err.message });
    }
  };
}

function paidHandler(staticServiceName, makePayload) {
  return (req, res) => {
    const serviceName = staticServiceName || req.serviceName;
    const service = serviceForName(serviceName);
    const seller = req.seller || walletForAgent(store, req.params.sellerId, "seller");
    const payment = req.payment || {};
    const payerWallet = store.byAddress.get(String(payment.payer || "").toLowerCase());
    const payerId = payerWallet?.agentId || req.claimedBuyer?.agentId || String(payment.payer || "unknown_payer");
    const roundId = String(req.body?.round_id || req.body?.roundId || "x402_agent_market");
    const resourceId = resourceIdFor(req, serviceName);
    const amount = Number(formatAtomicUsdc(payment.amount) || service.price);
    const product = makePayload(req, { seller, payerWallet, serviceName, service, payment });
    const receipt = buildReceipt({
      roundId,
      payerId,
      payeeId: seller.agentId,
      amount,
      paymentType: service.paymentType,
      resourceId,
      description: service.description,
      payment,
      sellerWallet: seller,
      buyerWallet: payerWallet || req.claimedBuyer,
      serviceName,
      metadata: {
        claimed_buyer_id: req.claimedBuyer?.agentId || "",
        seller_provider: seller.provider,
        buyer_provider: payerWallet?.provider || req.claimedBuyer?.provider || "",
      },
    });
    appendJsonl(receiptsPath, receipt);
    res.json({
      ok: true,
      rail: "x402_circle_gateway",
      service: serviceName,
      receipt,
      product,
    });
  };
}

function gatewayForSeller(seller) {
  const key = seller.normalizedAddress;
  if (!gateways.has(key)) {
    gateways.set(
      key,
      createGatewayMiddleware({
        sellerAddress: seller.address,
        facilitatorUrl: CIRCLE_FACILITATOR_URL,
        networks: [ARC_NETWORK],
        description: `Colony ant service sold by ${seller.agentId}`,
      }),
    );
  }
  return gateways.get(key);
}

function publicServices() {
  return Object.entries(SERVICES).map(([service_name, service]) => ({
    service_name,
    payment_type: service.paymentType,
    price_usdc: service.price,
    x402_price: `$${service.price}`,
    description: service.description,
  }));
}

function makeSummary(req, { seller }) {
  const topic = String(req.body?.topic || req.body?.room_id || "room");
  const evidence = Array.isArray(req.body?.evidence) ? req.body.evidence.slice(0, 5) : [];
  return {
    seller_id: seller.agentId,
    kind: "summary",
    topic,
    summary: evidence.length
      ? `${seller.agentId} summarized ${evidence.length} evidence item(s) for ${topic}.`
      : `${seller.agentId} summarized ${topic}.`,
    evidence_used: evidence,
  };
}

function makeAudit(req, { seller }) {
  const claimId = String(req.body?.claim_id || req.body?.resource_id || "claim");
  const grounded = Boolean(req.body?.evidence || req.body?.source_url || req.body?.source);
  return {
    seller_id: seller.agentId,
    kind: "audit",
    claim_id: claimId,
    grounded,
    verdict: grounded ? "grounded_dispute" : "needs_more_evidence",
  };
}

function makeFinding(req, { seller }) {
  const accessLevel = String(req.params.accessLevel);
  return {
    seller_id: seller.agentId,
    kind: "finding",
    access_level: accessLevel,
    finding_id: String(req.body?.finding_id || req.body?.resource_id || `${seller.agentId}:${accessLevel}:finding`),
    payload: req.body?.payload || {
      signal: accessLevel === "private" ? "premium_scout_signal" : "shared_scout_signal",
      confidence: accessLevel === "private" ? 0.72 : 0.58,
    },
  };
}

function resourceIdFor(req, serviceName) {
  return String(
    req.body?.resource_id
      || req.body?.room_id
      || req.body?.claim_id
      || req.body?.finding_id
      || `${serviceName}:${req.params.sellerId}`,
  );
}

function formatAtomicUsdc(value) {
  if (value === undefined || value === null || value === "") return "";
  const atomic = BigInt(value);
  const whole = atomic / 1_000_000n;
  const frac = (atomic % 1_000_000n).toString().padStart(6, "0").replace(/0+$/, "");
  return frac ? `${whole}.${frac}` : whole.toString();
}
