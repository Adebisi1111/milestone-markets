// Deploy the current contract, then resolve one YES and one NO market.
// One script so the address does not have to be copied between steps.
import { createClient, createAccount } from "genlayer-js";
import { testnetBradbury } from "genlayer-js/chains";
import { readFileSync } from "fs";
import { Wallet } from "ethers";

const wallet = Wallet.fromEncryptedJsonSync(
  readFileSync("/home/administrator/.genlayer/keystores/user_wallet.json", "utf8"),
  process.env.GLPASS
);
const client = createClient({ chain: testnetBradbury, account: createAccount(wallet.privateKey) });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ---- deploy ----
const code = readFileSync(new URL("./contracts/milestone_market.py", import.meta.url), "utf8");
const dHash = await client.deployContract({ code, args: [], value: 0n, gasLimit: 5000000n });
const dRc = await client.waitForTransactionReceipt({ hash: dHash, retries: 120, interval: 5000 });
const ADDR = (await client.getTransaction({ hash: dHash }))?.recipient;
console.log(`deploy tx=${dHash} status=${dRc?.status} address=${ADDR}`);

const REPO = "genlayerlabs/genlayer-js";
const SUPPORTED = "At least one pull request has been merged into this repository.";
const CONTRADICTED = "A quantum teleportation module exists at /src/quantum.py with full unit tests.";

async function write(fn, args) {
  const hash = await client.writeContract({ address: ADDR, functionName: fn, args, value: 0n, gasLimit: 5000000n });
  const rc = await client.waitForTransactionReceipt({ hash, retries: 180, interval: 5000 });
  console.log(`  ${fn} tx=${hash} status=${rc?.status}`);
  return rc;
}

const deadline = BigInt(Math.floor(Date.now() / 1000) + 60);
console.log("creating market 1 (expected YES)...");
await write("createMarket", [REPO, SUPPORTED, deadline]);
console.log("creating market 2 (expected NO)...");
await write("createMarket", [REPO, CONTRADICTED, deadline]);

console.log("waiting for the deadline...");
await sleep(70000);

for (const mid of ["milestone-1", "milestone-2"]) {
  console.log(`resolving ${mid}...`);
  try {
    await write("resolve", [mid]);
  } catch (e) {
    console.log(`  resolve threw: ${e.shortMessage || e.message}`);
  }
  const row = await client.readContract({ address: ADDR, functionName: "getMarket", args: [mid] });
  const why = await client.readContract({ address: ADDR, functionName: "getReasoning", args: [mid] });
  console.log(`  ${mid} -> ${row}`);
  console.log(`  reasoning: ${String(why).slice(0, 260)}`);
}
