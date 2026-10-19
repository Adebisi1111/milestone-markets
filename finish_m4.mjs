// Complete milestone-4 so no test artifact is left mid-lifecycle.
// Resolve (with retries) -> settle -> claim. The deployer's 0.1 GEN should
// leave the contract, restoring contractBalance to 0.
import { createClient, createAccount } from "genlayer-js";
import { testnetBradbury } from "genlayer-js/chains";
import { readFileSync } from "fs";
import { Wallet } from "ethers";

const ADDR = "0x203F67178a7B25803854D179d72Bf40Cfcdc2c88";
const ID = "milestone-4";
const KS = "/home/administrator/.genlayer/keystores/user_wallet.json";
const wallet = Wallet.fromEncryptedJsonSync(readFileSync(KS, "utf8"), process.env.GLPASS);
const account = createAccount(wallet.privateKey);
const client = createClient({ chain: testnetBradbury, account });
const r = (fn, args = []) => client.readContract({ address: ADDR, functionName: fn, args });
const sleep = (ms) => new Promise((res) => setTimeout(res, ms));
const gen = (w) => (Number(w) / 1e18).toFixed(6);

async function send(fn, args) {
  const hash = await client.writeContract({ address: ADDR, functionName: fn, args, gasLimit: 5000000n });
  const rc = await client.waitForTransactionReceipt({ hash, retries: 120, interval: 5000 });
  return `${rc?.statusName ?? rc?.status}/${rc?.txExecutionResultRaw ?? rc?.txExecutionResultName ?? ""}`;
}

const show = async (label) => {
  const m = JSON.parse(await r("getMarket", [ID]));
  console.log(`  ${label}: status=${m.status} outcome=${m.outcome || "-"} pool=${gen(m.pool)} contractBalance=${gen(await r("contractBalance"))} GEN`);
};

console.log("before:"); await show("m4");

if (JSON.parse(await r("getMarket", [ID])).status === "OPEN") {
  console.log("\nresolve:");
  for (let a = 1; a <= 8; a++) {
    console.log(`  attempt ${a}: ${await send("resolve", [ID])}`);
    const st = JSON.parse(await r("getMarket", [ID])).status;
    if (st !== "OPEN") { console.log(`  -> ${st}`); break; }
    await sleep(8000);
  }
  await show("after resolve");
}

if (JSON.parse(await r("getMarket", [ID])).status === "RESOLVED") {
  console.log("\nsettle:", await send("settle", [ID]));
  await show("after settle");
}

const m = JSON.parse(await r("getMarket", [ID]));
if (m.status === "SETTLED" || m.status === "VOID") {
  const claimed = await r("isClaimed", [ID, account.address]);
  if (String(claimed) === "0") {
    console.log("\nclaim:", await send("claim", [ID]));
  } else {
    console.log("\nalready claimed");
  }
}

console.log("\nfinal:"); await show("m4");
console.log("getCount:", await r("getCount"));
console.log("wallet:", gen(await client.getBalance({ address: account.address })), "GEN");
console.log("NOTE: payout finalizes later; contractBalance drops on finalization.");
