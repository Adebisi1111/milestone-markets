// PROOF: does a claim actually move GEN?
//
// Full lifecycle on the deployed contract with two distinct funded accounts:
//   create -> stake both sides -> deadline passes -> resolve (real AI consensus)
//   -> settle -> claim -> measure balances on BOTH sides
//
// The measurement that matters is the CLAIMER's balance between the moment the
// claim tx is accepted (gas already deducted) and the moment the external
// transfer lands (~2-3 min later). That delta is the payout and nothing else.
import { createClient, createAccount } from "genlayer-js";
import { testnetBradbury } from "genlayer-js/chains";
import { JsonRpcProvider, Wallet } from "ethers";
import { readFileSync } from "fs";

const ADDR = process.argv[2];
const GAS = 5000000n;
const RPC = "https://rpc-bradbury.genlayer.com";
const provider = new JsonRpcProvider(RPC);
const fmt = (v) => (Number(v) / 1e18).toFixed(6);

const main = Wallet.fromEncryptedJsonSync(
  readFileSync("/home/administrator/.genlayer/keystores/user_wallet.json", "utf8"),
  process.env.GLPASS
);
const throwaway = new Wallet(JSON.parse(readFileSync("/tmp/.throwaway.json", "utf8")).privateKey);
const mainClient = createClient({ chain: testnetBradbury, account: createAccount(main.privateKey) });
const tClient = createClient({ chain: testnetBradbury, account: createAccount(throwaway.privateKey) });

const read = (fn, args = []) => mainClient.readContract({ address: ADDR, functionName: fn, args });
const write = async (client, fn, args, value = 0n) => {
  const hash = await client.writeContract({ address: ADDR, functionName: fn, args, value, gasLimit: GAS });
  const rc = await client.waitForTransactionReceipt({ hash, retries: 150, interval: 5000 });
  return { hash, status: rc?.status };
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

console.log("contract :", ADDR);
console.log("main     :", main.address, "(will stake NO)");
console.log("throwaway:", throwaway.address, "(will stake YES, then claim)");

// ---------------------------------------------------------------- 1. create
const deadline = BigInt(Math.floor(Date.now() / 1000) + 240);
const c1 = await write(mainClient, "createMarket", [
  "genlayerlabs/genlayer-js",
  "At least one pull request has been merged into this repository.",
  deadline,
]);
console.log("\n[1] createMarket   status", c1.status, c1.hash);
const mid = "milestone-" + (await read("getCount"));
console.log("    market:", mid, "deadline", new Date(Number(deadline) * 1000).toISOString());

// ----------------------------------------------------------------- 2. stake
const mainStake = 300000000000000000n;   // 0.3 GEN on NO
const tStake = 500000000000000000n;      // 0.5 GEN on YES
const s1 = await write(mainClient, "stake", [mid, "NO"], mainStake);
console.log("[2] main stakes NO  0.3 status", s1.status);
const s2 = await write(tClient, "stake", [mid, "YES"], tStake);
console.log("    throwaway stakes YES 0.5 status", s2.status);

const afterStake = JSON.parse(await read("getMarket", [mid]));
console.log("    pool", fmt(afterStake.pool), "GEN | yes", fmt(afterStake.yes_pool), "| no", fmt(afterStake.no_pool));
console.log("    contractBalance", fmt(await read("contractBalance")), "GEN");
const expectedPayout = BigInt(afterStake.pool);   // sole YES staker takes the whole pool

// -------------------------------------------------- 3. wait for the deadline
const waitMs = Number(deadline) * 1000 - Date.now() + 20000;
console.log(`\n[3] waiting ${Math.round(waitMs / 1000)}s for the deadline to pass...`);
await sleep(Math.max(0, waitMs));

// --------------------------------------------------------------- 4. resolve
let outcome = "";
for (let round = 1; round <= 8 && !outcome; round++) {
  console.log(`[4] resolve round ${round} (AI consensus)...`);
  try {
    const r = await write(mainClient, "resolve", [mid]);
    const row = JSON.parse(await read("getMarket", [mid]));
    if (row.outcome === "YES" || row.outcome === "NO") outcome = row.outcome;
    else console.log("    not agreed yet (status " + r.status + ")");
  } catch (e) {
    console.log("    round failed:", (e.shortMessage || e.message || "").slice(0, 120));
  }
  if (!outcome) await sleep(5000);
}
console.log("    OUTCOME:", outcome || "STILL UNRESOLVED");
if (!outcome) process.exit(1);

// ---------------------------------------------------------------- 5. settle
const st = await write(mainClient, "settle", [mid]);
const settled = JSON.parse(await read("getMarket", [mid]));
console.log("[5] settle status", st.status, "-> market status", settled.status);
if (settled.status !== "SETTLED") { console.log("    not SETTLED, aborting"); process.exit(1); }

// ----------------------------------------------------------------- 6. claim
const contractBefore = await provider.getBalance(ADDR);
const claimerBefore = await provider.getBalance(throwaway.address);
console.log("\n[6] balances BEFORE claim");
console.log("    contract  ", fmt(contractBefore), "GEN");
console.log("    throwaway ", fmt(claimerBefore), "GEN");

const cl = await write(tClient, "claim", [mid]);
console.log("    claim tx status", cl.status, cl.hash);

const contractMid = await provider.getBalance(ADDR);
const claimerMid = await provider.getBalance(throwaway.address);
console.log("    balances right after the claim tx (gas deducted, transfer not yet landed)");
console.log("    contract  ", fmt(contractMid), "GEN");
console.log("    throwaway ", fmt(claimerMid), "GEN");

console.log("\n[7] waiting 180s for the external transfer to finalize...");
await sleep(180000);

const contractAfter = await provider.getBalance(ADDR);
const claimerAfter = await provider.getBalance(throwaway.address);
console.log("    balances AFTER the transfer");
console.log("    contract  ", fmt(contractAfter), "GEN");
console.log("    throwaway ", fmt(claimerAfter), "GEN");

// ------------------------------------------------------------ 8. the verdict
const claimerDelta = claimerAfter - claimerMid;
const contractDelta = contractMid - contractAfter;
console.log("\n================ RESULT ================");
console.log("expected payout          :", fmt(expectedPayout), "GEN");
console.log("claimer received         :", fmt(claimerDelta), "GEN");
console.log("contract paid out        :", fmt(contractDelta), "GEN");
console.log("claimer got the payout   :", claimerDelta === expectedPayout ? "PASS" : "FAIL");
console.log("contract lost the payout :", contractDelta === expectedPayout ? "PASS" : "FAIL");
console.log("isClaimed                :", await read("isClaimed", [mid, throwaway.address]));
console.log("contractBalance view     :", fmt(await read("contractBalance")), "GEN");
