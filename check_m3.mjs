// milestone-3's winner is a third account. Is that 0.8 GEN payout settled?
import { createClient, createAccount } from "genlayer-js";
import { testnetBradbury } from "genlayer-js/chains";
import { readFileSync } from "fs";
import { Wallet } from "ethers";

const ADDR = "0x203F67178a7B25803854D179d72Bf40Cfcdc2c88";
const KS = "/home/administrator/.genlayer/keystores/user_wallet.json";
const wallet = Wallet.fromEncryptedJsonSync(readFileSync(KS, "utf8"), process.env.GLPASS);
const client = createClient({ chain: testnetBradbury, account: createAccount(wallet.privateKey) });
const r = (fn, args = []) => client.readContract({ address: ADDR, functionName: fn, args });
const gen = (w) => (Number(w) / 1e18).toFixed(6);

const WIN3 = "0x2B70A945cdceb5BbfbF699a610090D503240cdc0";

console.log("milestone-3 winner:", WIN3);
console.log("  stake        :", gen(await r("getStake", ["milestone-3", WIN3])));
console.log("  isClaimed    :", await r("isClaimed", ["milestone-3", WIN3]));
console.log("  previewPayout:", gen(await r("previewPayout", ["milestone-3", WIN3])));
const bal = await client.getBalance({ address: WIN3 }).catch(() => null);
console.log("  balance      :", bal !== null ? gen(bal) + " GEN" : "n/a");

console.log("\ncontractBalance:", gen(await r("contractBalance")), "GEN");
console.log("\nInterpretation:");
const claimed = Number(await r("isClaimed", ["milestone-3", WIN3]));
const payout = Number(await r("previewPayout", ["milestone-3", WIN3]));
const cbal = Number(await r("contractBalance"));
if (claimed === 1) console.log("  milestone-3 payout already claimed -> 0.8 GEN left the contract.");
else if (payout > 0 && cbal < payout)
  console.log(`  *** milestone-3 winner is owed ${gen(payout)} GEN but the contract holds ${gen(cbal)} ***`);
else console.log("  milestone-3 winner has not claimed yet; contract can still cover it.");
