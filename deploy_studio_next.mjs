// Deploy MilestoneMarkets to Studio Next (chain 61997) — the hackathon target.
//
// gl.chains.studionet.extend() so the SDK inherits the consensus contract AND
// its ABI (a hand-built { id, rpcUrls } literal loses both).
// This genlayer-js build exposes no estimateTransactionFees/createFeesDistribution,
// so the deploy goes through plain deployContract, same as the Bradbury path.
import * as gl from "genlayer-js";
import { readFileSync } from "fs";
import { Wallet } from "ethers";

const wallet = Wallet.fromEncryptedJsonSync(
  readFileSync("/home/administrator/.genlayer/keystores/user_wallet.json", "utf8"),
  process.env.GLPASS
);
const account = gl.createAccount(wallet.privateKey);

const studioNext = gl.chains.studionet.extend({
  id: 61997,
  name: "Studio Next",
  rpcUrls: { default: { http: ["https://studio-next.genlayer.com/api"] } },
});

console.log(
  "addTransaction arities:",
  studioNext.consensusMainContract.abi.filter((x) => x.name === "addTransaction").map((x) => x.inputs?.length)
);

const client = gl.createClient({ chain: studioNext, account });
console.log("deployer:", account.address, "| balance:", await client.getBalance({ address: account.address }));

const code = readFileSync(new URL("./contracts/milestone_market.py", import.meta.url), "utf8");

const hash = await client.deployContract({ code, args: [], value: 0n, gasLimit: 5000000n });
console.log("deploy tx:", hash);

const rc = await client.waitForTransactionReceipt({ hash, retries: 150, interval: 5000 });
console.log("status:", rc?.status, rc?.statusName);

const tx = await client.getTransaction({ hash });
console.log("ADDRESS:", tx?.recipient);
