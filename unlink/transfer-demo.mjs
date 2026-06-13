// transfer-demo.mjs
//
// DRAFT — a private payment between two test Unlink accounts on a testnet.
// Reconstructed from https://docs.unlink.xyz (.md pages) on 2026-06-13; NOT yet run against
// the live SDK. Verify method names/shapes against the installed @unlink-xyz/sdk types.
//
// Flow: create two custodial accounts from mnemonics -> register both -> faucet-fund the
// sender privately -> private transfer A -> B -> print balances before/after.
//
// Prereqs (see README.md):
//   1. API key from https://dashboard.unlink.xyz
//   2. two throwaway mnemonics (cast wallet new-mnemonic)
//   3. cp .env.example .env  and fill values
//   4. npm install && node transfer-demo.mjs

import "dotenv/config";
import { createUnlinkAdmin } from "@unlink-xyz/sdk/admin";
// NOTE: docs show `account` from both @unlink-xyz/sdk/client and @unlink-xyz/sdk/crypto.
// Using /client here (the custodial server path). Switch to /crypto if the types say so.
import { account, createUnlinkClient } from "@unlink-xyz/sdk/client";

const {
  UNLINK_API_KEY,
  UNLINK_ENVIRONMENT = "base-sepolia",
  UNLINK_TEST_TOKEN,
  UNLINK_WALLET_A_MNEMONIC,
  UNLINK_WALLET_B_MNEMONIC,
  UNLINK_TRANSFER_AMOUNT = "1000000",
} = process.env;

function need(name, value) {
  if (!value) throw new Error(`Missing ${name} in unlink/.env`);
  return value;
}

const admin = createUnlinkAdmin({
  environment: UNLINK_ENVIRONMENT,
  apiKey: need("UNLINK_API_KEY", UNLINK_API_KEY),
});

// Build one custodial client per test wallet.
// NOTE: verified against @unlink-xyz/sdk@0.3.0-canary.598 — account.fromMnemonic takes
// ONLY { mnemonic } (appId/chainId are bound only in the MetaMask/signature derivations).
async function makeWallet(label, mnemonic) {
  const acct = account.fromMnemonic({
    mnemonic: need(`${label} mnemonic`, mnemonic),
  });
  const address = await acct.getAddress(); // "unlink1..."
  const client = createUnlinkClient({
    environment: UNLINK_ENVIRONMENT,
    account: acct,
    register: (payload) => admin.users.register(payload),
    authorizationToken: {
      provider: () => admin.authorizationTokens.issue({ unlinkAddress: address }),
    },
  });
  await client.ensureRegistered();
  console.log(`${label}: ${address}`);
  return { client, address };
}

async function main() {
  const token = need("UNLINK_TEST_TOKEN", UNLINK_TEST_TOKEN);

  const A = await makeWallet("Wallet A (sender)", UNLINK_WALLET_A_MNEMONIC);
  const B = await makeWallet("Wallet B (recipient)", UNLINK_WALLET_B_MNEMONIC);

  // 1. Privately fund the sender from the testnet faucet.
  console.log("\nFunding Wallet A privately via faucet...");
  await A.client.faucet.requestPrivateTokens({ token, amount: UNLINK_TRANSFER_AMOUNT });

  console.log("A before:", await A.client.balanceOf(token));
  console.log("B before:", await B.client.balanceOf(token));

  // 2. Private transfer A -> B.
  console.log(`\nTransferring ${UNLINK_TRANSFER_AMOUNT} (smallest unit) A -> B...`);
  const tx = await A.client.transfer({
    recipientAddress: B.address,
    token,
    amount: UNLINK_TRANSFER_AMOUNT,
  });
  const confirmed = await tx.wait();
  console.log("Transfer status:", confirmed.status); // "processed" | "failed"

  // 3. Resulting balances (balanceOf returns the smallest-unit amount as a string, or null).
  console.log("\nA after:", await A.client.balanceOf(token));
  console.log("B after:", await B.client.balanceOf(token));
}

main().catch((err) => {
  console.error("\nDemo failed:", err);
  process.exit(1);
});
