// sweep-to-treasury.mjs — withdraw the Unlink private balances (C, D) back to the Arc treasury.
// C = UNLINK_WALLET_A_MNEMONIC, D = UNLINK_WALLET_B_MNEMONIC (we control both).

import dotenv from "dotenv";
dotenv.config();                        // unlink/.env
dotenv.config({ path: "../arc/.env" });  // treasury address

import { createUnlinkAdmin } from "@unlink-xyz/sdk/admin";
import { account, createUnlinkClient } from "@unlink-xyz/sdk/client";

const ENV = "arc-testnet";
const TOKEN = process.env.UNLINK_TEST_TOKEN;
const TREASURY = process.env.ARC_TREASURY_ADDRESS;
const admin = createUnlinkAdmin({ environment: ENV, apiKey: process.env.UNLINK_API_KEY });

async function mk(mnemonic) {
  const acct = account.fromMnemonic({ mnemonic });
  const address = await acct.getAddress();
  const client = createUnlinkClient({
    environment: ENV, account: acct,
    register: (p) => admin.users.register(p),
    authorizationToken: { provider: () => admin.authorizationTokens.issue({ unlinkAddress: address }) },
  });
  await client.ensureRegistered();
  return { client, address };
}

console.log("Sweeping Unlink private balances -> treasury", TREASURY);
for (const [label, mnemonic] of [["C", process.env.UNLINK_WALLET_A_MNEMONIC], ["D", process.env.UNLINK_WALLET_B_MNEMONIC]]) {
  const w = await mk(mnemonic);
  const bal = await w.client.balanceOf(TOKEN);
  console.log(`\n${label} ${w.address}\n  private balance: ${bal}`);
  if (bal && BigInt(bal) > 0n) {
    const tx = await w.client.withdraw({ recipientEvmAddress: TREASURY, token: TOKEN, amount: bal });
    const r = await tx.wait();
    console.log(`  withdraw ${bal} -> treasury: ${r.status}`);
    console.log(`  ${label} private after: ${await w.client.balanceOf(TOKEN)}`);
  } else {
    console.log("  nothing to sweep");
  }
}
