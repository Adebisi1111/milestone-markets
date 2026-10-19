// Re-verify every on-chain fact the README cites, in one pass.
import { createClient, createAccount } from "genlayer-js";
import { testnetBradbury } from "genlayer-js/chains";
import { readFileSync } from "fs";
import { createHash } from "crypto";
import { Wallet } from "ethers";

const ADDR = "0x203F67178a7B25803854D179d72Bf40Cfcdc2c88";
const KS = "/home/administrator/.genlayer/keystores/user_wallet.json";
const wallet = Wallet.fromEncryptedJsonSync(readFileSync(KS, "utf8"), process.env.GLPASS);
const client = createClient({ chain: testnetBradbury, account: createAccount(wallet.privateKey) });
const r = (fn, args = []) => client.readContract({ address: ADDR, functionName: fn, args });

console.log("=== source parity ===");
const local = readFileSync(new URL("./contracts/milestone_market.py", import.meta.url), "utf8");
const code = await client.getContractCode(ADDR);
const live = typeof code === "string" ? code : String(code);
const h = (s) => createHash("sha256").update(s, "utf8").digest("hex");
console.log("live bytes :", Buffer.byteLength(live, "utf8"));
console.log("local bytes:", Buffer.byteLength(local, "utf8"));
console.log("live  sha256:", h(live));
console.log("local sha256:", h(local));
console.log("MATCH      :", h(live) === h(local) ? "YES" : "NO");

console.log("\n=== live state ===");
const count = await r("getCount");
console.log("getCount        :", count);
console.log("contractBalance :", await r("contractBalance"));
for (let i = 1; i <= Number(count); i++) {
  const id = `milestone-${i}`;
  const m = await r("getMarket", [id]);
  const parsed = typeof m === "string" ? JSON.parse(m) : m;
  console.log(`\n[${id}]`, JSON.stringify(parsed));
  try {
    const why = await r("getReasoning", [id]);
    console.log(`  reasoning: ${String(why).slice(0, 260)}`);
  } catch (e) { console.log("  reasoning: (none)"); }
}
console.log("\n=== deployer stake (must be none) ===");
try {
  console.log("getStake(milestone-1, deployer):", await r("getStake", ["milestone-1", "0x61fd0047595A30A067f1F21F3b28C4AE8A8e3Dc3"]));
  console.log("getStake(milestone-2, deployer):", await r("getStake", ["milestone-2", "0x61fd0047595A30A067f1F21F3b28C4AE8A8e3Dc3"]));
} catch (e) { console.log("stake read failed:", String(e).slice(0, 160)); }
