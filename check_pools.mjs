// Investigate the discrepancy: three markets with 0.8 GEN pools but a contract
// balance of 0. Who staked what, and has each pool actually been paid out?
import { createClient, createAccount } from "genlayer-js";
import { testnetBradbury } from "genlayer-js/chains";
import { readFileSync } from "fs";
import { Wallet } from "ethers";

const ADDR = "0x203F67178a7B25803854D179d72Bf40Cfcdc2c88";
const KS = "/home/administrator/.genlayer/keystores/user_wallet.json";
const wallet = Wallet.fromEncryptedJsonSync(readFileSync(KS, "utf8"), process.env.GLPASS);
const client = createClient({ chain: testnetBradbury, account: createAccount(wallet.privateKey) });
const r = (fn, args = []) => client.readContract({ address: ADDR, functionName: fn, args });

const MAIN = "0x61fd0047595A30A067f1F21F3b28C4AE8A8e3Dc3";
const THROW = "0x5e048eD4BFd5AEd9EA75a48f5abFF950E7f28dD7";
const gen = (w) => (Number(w) / 1e18).toFixed(6);

console.log("contractBalance:", gen(await r("contractBalance")), "GEN\n");

for (const id of ["milestone-1", "milestone-2", "milestone-3"]) {
  const m = JSON.parse(await r("getMarket", [id]));
  const dl = new Date(m.deadline * 1000).toISOString();
  console.log(`[${id}] status=${m.status} outcome=${m.outcome} pool=${gen(m.pool)} deadline=${dl}`);
  for (const [name, who] of [["main", MAIN], ["throwaway", THROW]]) {
    const st = await r("getStake", [id, who]);
    const cl = await r("isClaimed", [id, who]);
    const pv = await r("previewPayout", [id, who]);
    console.log(`   ${name.padEnd(10)} stake=${gen(st)} claimed=${cl} previewPayout=${gen(pv)}`);
  }
  try { console.log(`   positions: ${JSON.stringify(await r("getPositions", [id]))}`); } catch (e) {}
}

console.log("\n=== balances ===");
for (const [name, who] of [["main", MAIN], ["throwaway", THROW]]) {
  const b = await client.getBalance({ address: who }).catch(() => null);
  console.log(`${name.padEnd(10)} ${who} = ${b !== null ? gen(b) : "n/a"} GEN`);
}
