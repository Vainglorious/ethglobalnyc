// combined-route.mjs — one money route across BOTH Dynamic and Unlink on Arc testnet:
//
//   A (treasury, local key)
//     --Arc native USDC transfer-->        B (Dynamic V3 MPC wallet, server-signed)
//     --Unlink depositWithApproval-->      C (Unlink private account)
//     --Unlink private transfer-->         D (Unlink private account)
//
// B is created server-side via DynamicEvmWalletClient (we hold the key share) and signs via
// MPC. Its viem walletClient is reused as Unlink's EVM provider for the deposit.
//
// Reads dynamic/.env, ../arc/.env, ../unlink/.env.

import dotenv from "dotenv";
dotenv.config();                            // dynamic/.env
dotenv.config({ path: "../arc/.env" });      // treasury + RPC
dotenv.config({ path: "../unlink/.env" });   // unlink api key, mnemonics, token

import { DynamicEvmWalletClient } from "@dynamic-labs-wallet/node-evm";
import { privateKeyToAccount } from "viem/accounts";
import { createWalletClient, createPublicClient, http } from "viem";
import { createUnlinkAdmin } from "@unlink-xyz/sdk/admin";
import { account as unlinkAccount, createUnlinkClient, evm } from "@unlink-xyz/sdk/client";

const RPC = process.env.ARC_RPC_URL || "https://rpc.testnet.arc.network";
const USDC = process.env.UNLINK_TEST_TOKEN; // 0x3600... (6dp)
const PW = "colony-mpc-route-pw";

const arc = {
  id: 5042002, name: "Arc Testnet",
  nativeCurrency: { name: "USDC", symbol: "USDC", decimals: 18 },
  rpcUrls: { default: { http: [RPC] } },
};
const publicClient = createPublicClient({ chain: arc, transport: http(RPC) });
const ERC20_ABI = [{ name: "balanceOf", type: "function", stateMutability: "view", inputs: [{ type: "address" }], outputs: [{ type: "uint256" }] }];
const usdcOf = (addr) => publicClient.readContract({ address: USDC, abi: ERC20_ABI, functionName: "balanceOf", args: [addr] });

// --- A: treasury (local key) ---
const treasury = privateKeyToAccount(process.env.ARC_TREASURY_PRIVATE_KEY);
const treasuryWC = createWalletClient({ account: treasury, chain: arc, transport: http(RPC) });

// --- B: Dynamic server-side MPC wallet ---
const dyn = new DynamicEvmWalletClient({ environmentId: process.env.DYNAMIC_ENVIRONMENT_ID });
await dyn.authenticateApiToken(process.env.DYNAMIC_API_KEY);
const bWallet = await dyn.createWalletAccount({ thresholdSignatureScheme: "TWO_OF_TWO", password: PW, backUpToDynamic: true });
const bAddr = bWallet.walletMetadata.accountAddress;
const bWC = await dyn.getWalletClient({ walletMetadata: bWallet.walletMetadata, password: PW, externalServerKeyShares: bWallet.externalServerKeyShares, chainId: 5042002, rpcUrl: RPC });
const bEvm = evm.fromViem({ walletClient: bWC, publicClient });

// --- C, D: Unlink private accounts ---
const admin = createUnlinkAdmin({ environment: "arc-testnet", apiKey: process.env.UNLINK_API_KEY });
async function unlinkWallet(mnemonic, withEvm) {
  const acct = unlinkAccount.fromMnemonic({ mnemonic });
  const address = await acct.getAddress();
  const client = createUnlinkClient({
    environment: "arc-testnet", account: acct,
    ...(withEvm ? { evm: withEvm } : {}),
    register: (p) => admin.users.register(p),
    authorizationToken: { provider: () => admin.authorizationTokens.issue({ unlinkAddress: address }) },
  });
  await client.ensureRegistered();
  return { client, address };
}
const C = await unlinkWallet(process.env.UNLINK_WALLET_A_MNEMONIC, bEvm);
const D = await unlinkWallet(process.env.UNLINK_WALLET_B_MNEMONIC, null);

console.log("A treasury:", treasury.address);
console.log("B Dynamic :", bAddr);
console.log("C Unlink  :", C.address);
console.log("D Unlink  :", D.address);

// === ROUTE ===
console.log("\n[1] A -> B : treasury sends 3 USDC (native) to Dynamic B");
const h1 = await treasuryWC.sendTransaction({ to: bAddr, value: 3000000000000000000n });
await publicClient.waitForTransactionReceipt({ hash: h1 });
console.log("    B USDC balance:", (await usdcOf(bAddr)).toString());

console.log("\n[2] B -> C : Dynamic B deposits 2 USDC into Unlink (account C), signed via MPC");
const dep = await C.client.depositWithApproval({ token: USDC, amount: "2000000", evm: bEvm });
console.log("    deposit status:", (await dep.wait()).status);
console.log("    C private balance:", await C.client.balanceOf(USDC));

console.log("\n[3] C -> D : Unlink private transfer 1 USDC");
const tx = await C.client.transfer({ recipientAddress: D.address, token: USDC, amount: "1000000" });
console.log("    transfer status:", (await tx.wait()).status);
console.log("    C private:", await C.client.balanceOf(USDC), "| D private:", await D.client.balanceOf(USDC));

console.log("\nDONE: A(treasury) -> B(Dynamic MPC) -> C(Unlink) -> D(Unlink) ✅");
