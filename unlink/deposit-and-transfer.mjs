// deposit-and-transfer.mjs
//
// The faucet doesn't dispense Arc USDC, so instead we DEPOSIT real USDC from the funded
// Arc treasury wallet into Unlink (crediting Wallet A's private balance), then do the
// private A -> B transfer. Verified against @unlink-xyz/sdk@0.3.0-canary.598.
//
//   treasury USDC --depositWithApproval--> A (private) --transfer--> B (private)
//
// Reads unlink/.env (Unlink API key, mnemonics, token) and ../arc/.env (treasury key, RPC).

import dotenv from "dotenv";
dotenv.config();                       // unlink/.env
dotenv.config({ path: "../arc/.env" }); // arc/.env (treasury + RPC)

import { privateKeyToAccount } from "viem/accounts";
import { createWalletClient, createPublicClient, http } from "viem";
import { createUnlinkAdmin } from "@unlink-xyz/sdk/admin";
import { account, createUnlinkClient, evm } from "@unlink-xyz/sdk/client";

const ENV = process.env.UNLINK_ENVIRONMENT || "arc-testnet";
const TOKEN = process.env.UNLINK_TEST_TOKEN;                       // Arc USDC ERC-20 (6dp)
const RPC = process.env.ARC_RPC_URL || "https://rpc.testnet.arc.network";
const DEPOSIT_AMOUNT = process.env.UNLINK_DEPOSIT_AMOUNT || "2000000"; // 2 USDC
const TRANSFER_AMOUNT = process.env.UNLINK_TRANSFER_AMOUNT || "1000000"; // 1 USDC

function need(name, v) { if (!v) throw new Error(`Missing ${name}`); return v; }

// Arc testnet as a viem chain (native gas USDC = 18 decimals).
const arc = {
  id: 5042002,
  name: "Arc Testnet",
  nativeCurrency: { name: "USDC", symbol: "USDC", decimals: 18 },
  rpcUrls: { default: { http: [RPC] } },
};

const treasury = privateKeyToAccount(need("ARC_TREASURY_PRIVATE_KEY", process.env.ARC_TREASURY_PRIVATE_KEY));
const walletClient = createWalletClient({ account: treasury, chain: arc, transport: http(RPC) });
const publicClient = createPublicClient({ chain: arc, transport: http(RPC) });
const evmProvider = evm.fromViem({ walletClient, publicClient });

const admin = createUnlinkAdmin({ environment: ENV, apiKey: need("UNLINK_API_KEY", process.env.UNLINK_API_KEY) });

async function makeWallet(label, mnemonic, withEvm) {
  const acct = account.fromMnemonic({ mnemonic: need(`${label} mnemonic`, mnemonic) });
  const address = await acct.getAddress();
  const client = createUnlinkClient({
    environment: ENV,
    account: acct,
    ...(withEvm ? { evm: evmProvider } : {}),
    register: (p) => admin.users.register(p),
    authorizationToken: { provider: () => admin.authorizationTokens.issue({ unlinkAddress: address }) },
  });
  await client.ensureRegistered();
  console.log(`${label}: ${address}`);
  return { client, address };
}

async function main() {
  need("UNLINK_TEST_TOKEN", TOKEN);
  console.log("Treasury EVM:", treasury.address, "| token:", TOKEN, "| env:", ENV);

  const A = await makeWallet("Wallet A (sender)", process.env.UNLINK_WALLET_A_MNEMONIC, true);
  const B = await makeWallet("Wallet B (recipient)", process.env.UNLINK_WALLET_B_MNEMONIC, false);

  console.log("\nA private before:", await A.client.balanceOf(TOKEN));
  console.log("B private before:", await B.client.balanceOf(TOKEN));

  // 1. Deposit real USDC from the treasury into A's private balance.
  console.log(`\nDepositing ${DEPOSIT_AMOUNT} (smallest unit) USDC from treasury -> A ...`);
  const dep = await A.client.depositWithApproval({ token: TOKEN, amount: DEPOSIT_AMOUNT, evm: evmProvider });
  const depConfirmed = await dep.wait();
  console.log("Deposit status:", depConfirmed.status);
  console.log("A private after deposit:", await A.client.balanceOf(TOKEN));

  // 2. Private transfer A -> B.
  console.log(`\nPrivate transfer ${TRANSFER_AMOUNT} (1 USDC) A -> B ...`);
  const tx = await A.client.transfer({ recipientAddress: B.address, token: TOKEN, amount: TRANSFER_AMOUNT });
  const confirmed = await tx.wait();
  console.log("Transfer status:", confirmed.status);

  // 3. Final balances.
  console.log("\nA private after:", await A.client.balanceOf(TOKEN));
  console.log("B private after:", await B.client.balanceOf(TOKEN));
}

main().catch((e) => { console.error("\nFailed:", e?.message || e); process.exit(1); });
