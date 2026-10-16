// Inspect a transaction to find out why a resolve did not commit.
import { createClient, createAccount } from "genlayer-js";
import { testnetBradbury } from "genlayer-js/chains";
import { readFileSync } from "fs";
import { Wallet } from "ethers";

const wallet = Wallet.fromEncryptedJsonSync(
  readFileSync("/home/administrator/.genlayer/keystores/user_wallet.json", "utf8"),
  process.env.GLPASS
);
const client = createClient({ chain: testnetBradbury, account: createAccount(wallet.privateKey) });

const hash = process.argv[2];
const tx = await client.getTransaction({ hash });
console.log(JSON.stringify(tx, (k, v) => (typeof v === "bigint" ? v.toString() : v), 2).slice(0, 4000));
