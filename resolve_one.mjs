// Retry resolve() on a market and report the row afterwards.
import { createClient, createAccount } from "genlayer-js";
import { testnetBradbury } from "genlayer-js/chains";
import { readFileSync } from "fs";
import { Wallet } from "ethers";

const wallet = Wallet.fromEncryptedJsonSync(
  readFileSync("/home/administrator/.genlayer/keystores/user_wallet.json", "utf8"),
  process.env.GLPASS
);
const client = createClient({ chain: testnetBradbury, account: createAccount(wallet.privateKey) });

const ADDR = process.argv[2];
const MID = process.argv[3];

for (let attempt = 1; attempt <= 3; attempt++) {
  console.log(`attempt ${attempt}...`);
  try {
    const hash = await client.writeContract({
      address: ADDR,
      functionName: "resolve",
      args: [MID],
      value: 0n,
      gasLimit: 5000000n,
    });
    const receipt = await client.waitForTransactionReceipt({ hash, retries: 180, interval: 5000 });
    console.log(`  tx=${hash} status=${receipt?.status} ${receipt?.statusName ?? ""}`);
    const row = await client.readContract({ address: ADDR, functionName: "getMarket", args: [MID] });
    console.log(`  row: ${row}`);
    if (String(row).split("|")[3] === "YES" || String(row).split("|")[3] === "NO") {
      const why = await client.readContract({ address: ADDR, functionName: "getReasoning", args: [MID] });
      console.log(`  reasoning: ${String(why).slice(0, 400)}`);
      break;
    }
  } catch (e) {
    console.log(`  error: ${e.shortMessage || e.message}`);
  }
}
