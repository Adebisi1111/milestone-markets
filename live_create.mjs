// Live end-to-end: open a market on Bradbury and read it back.
import { createClient, createAccount } from "genlayer-js";
import { testnetBradbury } from "genlayer-js/chains";
import { readFileSync } from "fs";
import { Wallet } from "ethers";

const KS = "/home/administrator/.genlayer/keystores/user_wallet.json";
const ADDR = process.argv[2];

const wallet = Wallet.fromEncryptedJsonSync(readFileSync(KS, "utf8"), process.env.GLPASS);
const account = createAccount(wallet.privateKey);
const client = createClient({ chain: testnetBradbury, account });

const deadline = BigInt(Math.floor(Date.now() / 1000) + 900);

const hash = await client.writeContract({
  address: ADDR,
  functionName: "createMarket",
  args: ["genlayerlabs/genlayer-js", "Ship TypeScript typings for readContract", deadline],
  value: 0n,
  gasLimit: 5000000n,
});
console.log("createMarket tx:", hash);

const receipt = await client.waitForTransactionReceipt({ hash, retries: 120, interval: 5000 });
console.log("status:", receipt?.status ?? receipt?.txExecutionResultName, receipt?.statusName ?? "");

const count = await client.readContract({ address: ADDR, functionName: "getCount", args: [] });
console.log("getCount:", count);

const row = await client.readContract({ address: ADDR, functionName: "getMarket", args: ["milestone-1"] });
console.log("getMarket:", row);
