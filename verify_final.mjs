// Final verification of the Bradbury deployment the submission will cite.
import { createClient } from "genlayer-js";
import { testnetBradbury } from "genlayer-js/chains";

const ADDR = "0xD5Ac66d80CaA33413502c9bb2eCc4dA9c8F8Cd2c";
const client = createClient({ chain: testnetBradbury });

console.log("=== getContractCode (source on chain, not a proxy) ===");
try {
  const code = await client.getContractCode(ADDR);
  const src = typeof code === "string" ? code : JSON.stringify(code);
  console.log("  length:", src.length);
  console.log("  has class MilestoneMarkets:", src.includes("MilestoneMarkets"));
  console.log("  has prompt_comparative:", src.includes("prompt_comparative"));
  console.log("  has git/trees HEAD:", src.includes("git/trees/HEAD"));
} catch (e) {
  console.log("  getContractCode failed:", e.shortMessage || e.message);
}

console.log("\n=== reads ===");
console.log("  getCount:", await client.readContract({ address: ADDR, functionName: "getCount", args: [] }));
for (let i = 1; i <= 3; i++) {
  const id = "milestone-" + i;
  const row = await client.readContract({ address: ADDR, functionName: "getMarket", args: [id] });
  const p = String(row).split("|");
  console.log(`  ${id}: repo=${p[0]} status=${p[2]} outcome=${p[3] || "-"}`);
}

console.log("\n=== explorer path check ===");
console.log("  address path in README must 200 — checked separately with curl");
