// Set up a second, distinct, funded account for the balance-delta proof.
// The steward rule: never reuse one account across scenarios, and never make the
// deployer a participant (its stake would read as the submitter trapping funds).
import { JsonRpcProvider, Wallet } from "ethers";
import { readFileSync, writeFileSync, existsSync } from "fs";

const RPC = "https://rpc-bradbury.genlayer.com";
const provider = new JsonRpcProvider(RPC);
const main = Wallet.fromEncryptedJsonSync(
  readFileSync("/home/administrator/.genlayer/keystores/user_wallet.json", "utf8"),
  process.env.GLPASS
).connect(provider);

const KS = "/tmp/.throwaway.json";
let throwaway;
if (existsSync(KS)) {
  throwaway = new Wallet(JSON.parse(readFileSync(KS, "utf8")).privateKey, provider);
} else {
  throwaway = Wallet.createRandom(provider);
  writeFileSync(KS, JSON.stringify({ privateKey: throwaway.privateKey }), { mode: 0o600 });
}

const mainBal = await provider.getBalance(main.address);
const tBal = await provider.getBalance(throwaway.address);
console.log("main      :", main.address, "balance", Number(mainBal) / 1e18, "GEN");
console.log("throwaway :", throwaway.address, "balance", Number(tBal) / 1e18, "GEN");

// Fund the throwaway if it is light: it needs stake + gas.
const need = 2n * 10n ** 18n;
if (tBal < need) {
  const send = await main.sendTransaction({ to: throwaway.address, value: need - tBal });
  console.log("funding tx:", send.hash);
  await send.wait();
  console.log("throwaway funded to", Number(await provider.getBalance(throwaway.address)) / 1e18, "GEN");
}
