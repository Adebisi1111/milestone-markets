// Live consensus test, both verdict directions.
//
//   market 2 -> a claim the repository clearly supports  -> expect YES
//   market 3 -> a claim the repository clearly contradicts -> expect NO
//
// Both resolve against the same repository, so only the criteria differ.
import { createClient, createAccount } from "genlayer-js";
import { testnetBradbury } from "genlayer-js/chains";
import { readFileSync } from "fs";
import { Wallet } from "ethers";

const KS = "/home/administrator/.genlayer/keystores/user_wallet.json";
const ADDR = process.argv[2];
const REPO = "genlayerlabs/genlayer-js";

const wallet = Wallet.fromEncryptedJsonSync(readFileSync(KS, "utf8"), process.env.GLPASS);
const account = createAccount(wallet.privateKey);
const client = createClient({ chain: testnetBradbury, account });

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function write(fn, args) {
  const hash = await client.writeContract({ address: ADDR, functionName: fn, args, value: 0n, gasLimit: 5000000n });
  const receipt = await client.waitForTransactionReceipt({ hash, retries: 180, interval: 5000 });
  console.log(`  ${fn} tx=${hash} status=${receipt?.status} ${receipt?.statusName ?? ""}`);
  return receipt;
}

const SUPPORTED = "At least one pull request has been merged into this repository.";
const CONTRADICTED = "A quantum teleportation module exists at /src/quantum.py with full unit tests.";

// A short deadline so resolution is reachable inside this run.
const deadline = BigInt(Math.floor(Date.now() / 1000) + 60);

console.log("creating market 1 (expected YES)...");
await write("createMarket", [REPO, SUPPORTED, deadline]);
console.log("creating market 2 (expected NO)...");
await write("createMarket", [REPO, CONTRADICTED, deadline]);

console.log("waiting for the deadline to pass...");
await sleep(70000);

for (const mid of ["milestone-1", "milestone-2"]) {
  console.log(`resolving ${mid}...`);
  await write("resolve", [mid]);
  const outcome = await client.readContract({ address: ADDR, functionName: "getMarket", args: [mid] });
  const why = await client.readContract({ address: ADDR, functionName: "getReasoning", args: [mid] });
  console.log(`  ${mid} -> ${outcome}`);
  console.log(`  reasoning: ${String(why).slice(0, 300)}`);
}
