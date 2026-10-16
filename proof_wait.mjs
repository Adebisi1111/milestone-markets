// Wait for the claim tx to FINALIZE, then report the real balance deltas.
// External messages execute on finalization, and Bradbury finalization has been
// measured at ~20 min to ~2.4 h -- so this polls for up to 3 hours.
import { createClient } from "genlayer-js";
import { testnetBradbury } from "genlayer-js/chains";
import { JsonRpcProvider } from "ethers";

const CLAIM = process.argv[2];
const CONTRACT = process.argv[3];
const CLAIMER = process.argv[4];

const p = new JsonRpcProvider("https://rpc-bradbury.genlayer.com");
const c = createClient({ chain: testnetBradbury });
const fmt = (v) => (Number(v) / 1e18).toFixed(6);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const c0 = await p.getBalance(CONTRACT);
const k0 = await p.getBalance(CLAIMER);
console.log(`t0 contract ${fmt(c0)}  claimer ${fmt(k0)}`);
console.log("waiting for FINALIZED (status 7)...");

for (let i = 0; i < 120; i++) {
  const tx = await c.getTransaction({ hash: CLAIM });
  const cb = await p.getBalance(CONTRACT);
  const kb = await p.getBalance(CLAIMER);
  const moved = cb !== c0 || kb !== k0;
  console.log(
    `${new Date().toISOString().slice(11, 19)}  tx ${tx.status} ${tx.statusName}  |  contract ${fmt(cb)}  claimer ${fmt(kb)}${moved ? "   <-- MOVED" : ""}`
  );
  if (tx.status === 7 || moved) {
    console.log("\n=========== FINAL ===========");
    console.log("contract delta :", fmt(c0 - cb), "GEN out");
    console.log("claimer  delta :", fmt(kb - k0), "GEN in");
    process.exit(0);
  }
  await sleep(90000);
}
console.log("still not finalized after 3h");
