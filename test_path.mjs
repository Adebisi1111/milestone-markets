// Run the exact tester path end to end, to prove it is completable in one sitting.
//
// Creates a market with a deadline ~2 minutes out, stakes YES, waits for the
// deadline, resolves, settles and claims — reporting each step's real result.
import { createClient, createAccount } from "genlayer-js";
import { testnetBradbury } from "genlayer-js/chains";
import { readFileSync } from "fs";
import { Wallet } from "ethers";

const ADDR = "0x203F67178a7B25803854D179d72Bf40Cfcdc2c88";
const KS = "/home/administrator/.genlayer/keystores/user_wallet.json";
const wallet = Wallet.fromEncryptedJsonSync(readFileSync(KS, "utf8"), process.env.GLPASS);
const account = createAccount(wallet.privateKey);
const client = createClient({ chain: testnetBradbury, account });
const r = (fn, args = []) => client.readContract({ address: ADDR, functionName: fn, args });
const sleep = (ms) => new Promise((res) => setTimeout(res, ms));
const gen = (w) => (Number(w) / 1e18).toFixed(6);

const REPO = "genlayerlabs/genlayer-js";
const CRITERIA = "At least one pull request has been merged into this repository.";
const MINUTES = 2;
const STAKE = BigInt(Math.round(0.1 * 1e18));

async function send(fn, args, value = 0n) {
  const hash = await client.writeContract({ address: ADDR, functionName: fn, args, value, gasLimit: 5000000n });
  const rc = await client.waitForTransactionReceipt({ hash, retries: 120, interval: 5000 });
  return { hash, status: rc?.statusName ?? rc?.status, result: rc?.txExecutionResultRaw ?? rc?.txExecutionResultName ?? "" };
}

console.log("deployer:", account.address);
console.log("contract balance before:", gen(await r("contractBalance")), "GEN");
const before = Number(await r("getCount"));
const id = `milestone-${before + 1}`;
console.log("will create:", id);

// STEP 3 — create a market whose deadline is ~2 minutes out
const deadline = BigInt(Math.floor(Date.now() / 1000) + MINUTES * 60);
console.log(`\nSTEP 3 create: deadline in ${MINUTES} min -> ${new Date(Number(deadline) * 1000).toISOString()}`);
console.log("  ", await send("createMarket", [REPO, CRITERIA, deadline]));
console.log("   getMarket:", JSON.stringify(JSON.parse(await r("getMarket", [id]))).slice(0, 220));

// STEP 4 — stake YES
console.log("\nSTEP 4 stake YES 0.1 GEN");
console.log("  ", await send("stake", [id, "YES"], STAKE));
const m1 = JSON.parse(await r("getMarket", [id]));
console.log(`   pool=${gen(m1.pool)} yes=${gen(m1.yes_pool)} no=${gen(m1.no_pool)} status=${m1.status}`);
console.log("   contract balance:", gen(await r("contractBalance")), "GEN");

// STEP 5 — wait for the deadline
const waitMs = Math.max(0, Number(deadline) * 1000 - Date.now()) + 20000;
console.log(`\nSTEP 5 waiting ${Math.round(waitMs / 1000)}s for the deadline to pass...`);
await sleep(waitMs);
console.log("   market now:", JSON.parse(await r("getMarket", [id])).status);

// STEP 6 — resolve (consensus, with retries)
console.log("\nSTEP 6 resolve");
let settled = false;
for (let a = 1; a <= 5 && !settled; a++) {
  const out = await send("resolve", [id]);
  const st = JSON.parse(await r("getMarket", [id])).status;
  console.log(`   attempt ${a}: ${out.status} ${out.result} -> status=${st}`);
  if (st !== "OPEN") { settled = true; break; }
  await sleep(10000);
}
const m2 = JSON.parse(await r("getMarket", [id]));
console.log("   outcome:", m2.outcome || "(none)");
console.log("   reasoning:", String(await r("getReasoning", [id])).slice(0, 240));

// STEP 7 — settle
console.log("\nSTEP 7 settle");
console.log("  ", await send("settle", [id]));
const m3 = JSON.parse(await r("getMarket", [id]));
console.log(`   status=${m3.status} outcome=${m3.outcome}`);
console.log("   previewPayout(deployer):", gen(await r("previewPayout", [id, account.address])));

// STEP 8 — claim
console.log("\nSTEP 8 claim");
console.log("  ", await send("claim", [id]));
console.log("   isClaimed:", await r("isClaimed", [id, account.address]));
console.log("   contract balance after:", gen(await r("contractBalance")), "GEN");
console.log("   wallet balance:", gen(await client.getBalance({ address: account.address })), "GEN");
console.log("\nNOTE: the payout lands on FINALIZATION, tens of minutes later.");
