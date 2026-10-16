// Open a market with a future deadline so the staking UI has something to show.
import { createClient, createAccount } from "genlayer-js";
import { testnetBradbury } from "genlayer-js/chains";
import { readFileSync } from "fs";
import { Wallet } from "ethers";

const wallet = Wallet.fromEncryptedJsonSync(
  readFileSync("/home/administrator/.genlayer/keystores/user_wallet.json", "utf8"),
  process.env.GLPASS
);
const client = createClient({ chain: testnetBradbury, account: createAccount(wallet.privateKey) });
const ADDR = process.argv[2];

const deadline = BigInt(Math.floor(Date.now() / 1000) + 3 * 24 * 3600);
const hash = await client.writeContract({
  address: ADDR,
  functionName: "createMarket",
  args: [
    "genlayerlabs/genlayer-js",
    "Publish a CHANGELOG.md at the repository root and cut a tagged release",
    deadline,
  ],
  value: 0n,
  gasLimit: 5000000n,
});
const rc = await client.waitForTransactionReceipt({ hash, retries: 120, interval: 5000 });
console.log(`createMarket tx=${hash} status=${rc?.status}`);
console.log("count:", await client.readContract({ address: ADDR, functionName: "getCount", args: [] }));
