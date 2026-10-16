// Deploy a contract from an arbitrary path, to test the size cap.
import { createClient, createAccount } from "genlayer-js";
import { testnetBradbury } from "genlayer-js/chains";
import { readFileSync } from "fs";
import { Wallet } from "ethers";

const path = process.argv[2];
const wallet = Wallet.fromEncryptedJsonSync(
  readFileSync("/home/administrator/.genlayer/keystores/user_wallet.json", "utf8"),
  process.env.GLPASS
);
const client = createClient({ chain: testnetBradbury, account: createAccount(wallet.privateKey) });
const code = readFileSync(path, "utf8");
console.log(`${path}  bytes=${Buffer.byteLength(code)}`);

try {
  const hash = await client.deployContract({ code, args: [], value: 0n, gasLimit: 5000000n });
  const rc = await client.waitForTransactionReceipt({ hash, retries: 120, interval: 5000 });
  const tx = await client.getTransaction({ hash });
  console.log("  RESULT: deployed, status", rc?.status, "address", tx?.recipient);
} catch (e) {
  console.log("  RESULT: FAILED —", (e.shortMessage || e.message || "").slice(0, 200));
}
