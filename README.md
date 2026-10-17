# MilestoneMarkets

Prediction markets on **open-source delivery**.

Users bet YES or NO on whether a named repository ships a milestone by a
deadline. There is no human judge and no oracle: GenLayer's AI validators read
the repository's own commits, pull requests and file tree and decide whether
the criteria were met — then winners are paid automatically.

## Why GenLayer

A market on "did this team ship the feature on time" cannot be settled by a
price feed. The answer lives in code — commit dates, merged pull requests,
whether the tests the milestone asked for actually exist. Settling it means
**reading and judging unstructured evidence**, which is what comparative
consensus is for.

The important property is what the validators read. Nobody chooses the evidence:

| | A market resolved from a cited URL | MilestoneMarkets |
|---|---|---|
| Who picks the evidence | the market creator | nobody — the contract builds the GitHub URLs from the repo name |
| What the validators see | whatever the creator pointed at | the repository's commits, pull requests and files |
| Trust assumption | the creator chose an honest source | the repository is the source |

There is no method on the contract that accepts a URL. `createMarket` takes a
repository (`owner/name`), the milestone criteria, and a deadline.

## Lifecycle

1. **`createMarket(repo, milestone, deadline)`** — open a market. `deadline` is
   unix seconds and must be in the future. No evidence URL is accepted.
2. **`stake(marketId, side)`** — send GEN on `YES` or `NO`. Staking closes when
   the deadline passes.
3. **`resolve(marketId)`** — after the deadline, every validator independently
   fetches `api.github.com/repos/<repo>/commits`, `/pulls` and the file tree,
   runs the evaluator prompt below against the milestone criteria, and agrees
   through `gl.eq_principle.prompt_comparative`. If they cannot agree, the market
   stays `OPEN` rather than guessing.
4. **`settle(marketId)`** — lock the outcome. If the winning side drew no stake,
   the market is `VOID` instead, so nobody's GEN is stranded.
5. **`claim(marketId)`** — the winner pulls their parimutuel share in native GEN.
6. **`void(marketId)`** — once a market is 30 days past its deadline and still
   unresolved, anyone can void it and every staker takes their own stake back.

**Every market reaches a state where staker GEN comes back out.** There is no
path — no winning staker, no agreeing validators — that locks funds in the
contract forever.

## The app

Two pages, both deployed on GitHub Pages:

| | |
|---|---|
| **Landing** — https://adebisi1111.github.io/milestone-markets/ | what the product is, how a market resolves, the evaluator prompt verbatim, and the proof |
| **App** — https://adebisi1111.github.io/milestone-markets/app.html | the tool |

The landing does the explaining so the app can stay a tool. The previous
single-page app is kept in the repo as `index.v1.html` — a one-file revert if the
older direction is ever preferred.

### What the app does

- **Wallet balance in the nav.** The connected account's GEN, read from the chain
  and refreshed after every write, so the number on screen is never stale.
- **A “Your position” panel.** Wallet / staked / claimable / markets, plus a row
  per market. This is the screen that answers “do I have money waiting?”
- **Transaction toasts.** Submitted → accepted → failed, with the reason on
  failure. A failed write is impossible to miss.
- **Finalization-aware claims.** A claim is an external message, so the GEN
  arrives on finalization (tens of minutes). The UI says so and watches the
  balance, rather than presenting a working payout as broken.
- **Chain guard.** On connect the page switches — or adds — the target chain in
  the wallet, so a user on the wrong network is corrected *before* they sign.
- **Loading skeletons**, not a text flash.

### Design

One design system, declared as custom properties at the top of both pages: a
near-black surface scale, a violet→mint accent, a radius scale (8/12/18) and a
type scale with an uppercase micro-label tier. The wordmark is an original SVG
mark — a stepped path from a start node to a milestone node — not initials in a
coloured square.

No CSS framework and no build step: each page is a single self-contained file.

### The frontend asks the wallet to sign

Verified with a mock EIP-1193 provider injected before page load:

```
wallet calls: ["eth_accounts", "eth_chainId", "eth_sendTransaction"]
```

`eth_requestAccounts` and `wallet_switchEthereumChain` fire on *connect*, so they
prove nothing about a transaction. `eth_sendTransaction` is the assertion that
matters. The page also does not navigate away, and there is no link to a Studio
deploy UI anywhere in it.

## The evaluator prompt

Sent to every validator, verbatim, with the repository digest and the criteria:

```
You are an expert software engineer acting as an autonomous GenLayer validator.
Your task is to objectively determine if an open-source development milestone
has been successfully achieved.

### DATA SOURCED FROM GITHUB:
<repository digest>

### SUCCESS CRITERIA TO EVALUATE:
"<milestone>"

### RULES FOR EVALUATION:
1. Base your evaluation strictly on the provided GitHub data. Do not hallucinate
   or assume facts.
2. The code must be explicitly merged or completed within the repository text.
3. If the criteria mentions specific technical requirements (e.g., unit tests,
   specific files, or features), verify that they actually exist in the data
   text. Empty files or uncompleted PRs count as a failure (NO).
4. The milestone must have been completed ON OR BEFORE the deadline. A merge
   dated after the deadline is late and counts as NO.

### OUTPUT FORMAT:
Reply in valid JSON with exactly two keys: "outcome" and "reasoning".
The "outcome" value must be strictly either "YES" or "NO".
```

Rule 4 and the `MILESTONE DEADLINE (UTC)` line in the digest are the "on time"
half of the question — the digest carries each merge's `merged_at`, so the
validator compares dates rather than assuming.

## Design notes

- **The digest is filtered, not raw.** Only stable fields survive (short sha,
  author date, first message line, PR number/state/`merged_at`/title, and the
  repo's file tree) and each list is capped. A raw API response differs between
  validators as the repo moves, and a varying input starves the equivalence
  principle of agreement.
- **The file tree is load-bearing.** Live testing showed a criterion naming a
  file that does *not* exist (`/src/quantum.py`) could not be resolved from
  commit messages and PR titles alone — they carry no paths, so the validator
  has nothing to check rule 3 against. Adding
  `git/trees/HEAD?recursive=1` gives it the paths.
- **The digest must stay small.** The first live attempt at that same claim
  failed four times with `LEADER_TIMEOUT` / `VALIDATORS_TIMEOUT` (status 13/12,
  zero votes) — not a disagreement, a time-out. Every fetch and every prompt
  token is validator wall-clock, so the caps here are deliberately tight
  (10 commits, 10 PRs, 60 paths) and the branch is read from `HEAD` rather than
  a second request for the default branch.
- **`UNKNOWN` is checked before `NO`.** A substring scan would match the `NO`
  inside `UNKNOWN` and silently resolve an unsettled milestone against NO.
- **Flat `TreeMap`s with string keys.** Nested maps and in-place dataclass
  mutation are the two storage patterns that break consensus.
- **Payout is parimutuel** — winners split the whole pool proportionally:
  `winning_stake * total_pool // winning_pool`.
- **Paying an EOA is an external message**, so it goes through the EVM
  interface. `gl.get_contract_at(wallet).emit_transfer()` is IC→IC only and
  silently moves nothing.
- **Time** follows docs.genlayer.com "Transaction Context": the GenVM clock is
  pinned to the transaction datetime and is identical across validators, so
  `int(datetime.now(timezone.utc).timestamp())` is deterministic and safe for a
  deadline comparison.
- **Views return JSON, not delimited strings.** The criteria is stored
  verbatim, so a `|` inside it would shift every later field of a `|`-delimited
  read and make the UI render the wrong state. `getMarket` returns JSON.

## Tests

27 direct-mode tests, no network and no chain — the GitHub API and the LLM are
mocked and the clock is warped with `direct_vm.warp(...)` so deadlines can be
crossed inside a test.

```bash
gltest tests/direct -q
# 27 passed
```

(`python3 -m pytest` is not the right entry point here: the GenLayer test runner
ships with the `genlayer` CLI, and `gltest` is the command that resolves it.)

One environment detail the suite handles explicitly: in direct mode a payable
call does **not** credit value to the contract, so `self.balance` stays 0 however
much `stake` sends. The `stake` helper funds the contract with
`direct_vm.deal(...)` to mirror what the chain does — otherwise `claim`'s balance
guard correctly refuses every payout.

Covered: creation validation, staking both sides, bad side, zero value, staking
after the deadline, resolve before the deadline, resolve YES, resolve NO,
resolve is not repeatable, the caller supplies no evidence source, parimutuel
payout math, loser cannot claim, double-claim rejected, claim before settlement
rejected — plus four fund-safety cases:

- **No winning staker.** Outcome YES with only NO backed: `settle` returns
  `VOID` and the NO staker gets their stake back. Paying nobody would otherwise
  hold it forever.
- **Unresolved market.** 30 days past the deadline and still `OPEN`: anyone can
  `void` it and every staker is refunded. Inside the grace window it is not
  voidable, and a resolved market can never be voided — so a creator cannot dodge
  a verdict they dislike.
- **Separator in the criteria.** `Ship A | B | C` no longer shifts the other
  fields of a read.
- **Under-funded payout.** An `emit_transfer` for more than the contract holds is
  a silent no-op — it returns success and moves nothing. `claim` now checks
  `self.balance` **before** marking the claim, so a short contract refuses and the
  winner can retry, instead of being recorded as paid, receiving zero, and being
  locked out by `Already claimed`.

Each of these is mutation-checked. Removing the `VOID` branch in `settle` turns
`test_no_winning_stake_voids_instead_of_stranding_funds` red; removing the
balance guard turns
`test_claim_refuses_and_does_not_burn_the_claim_when_balance_is_short` red.

## Known limitation

GitHub's unauthenticated API allows 60 requests/hour per IP. Each validator
fetches independently, so a heavily-resolved market can exhaust a validator's
budget; the digest degrades to `(commits could not be fetched)` and the verdict
falls back to whatever evidence did arrive. A production deployment would use a
token or a mirror.

## Run it locally

Both pages are static and the app talks to the chain directly, so there is no
backend and no build step:

```bash
python3 -m http.server 8899
# http://127.0.0.1:8899/            -> landing
# http://127.0.0.1:8899/app.html    -> app
```

Reads work with no wallet. Writes need a browser wallet on the target chain with
GEN for gas.

## Deploy

```bash
GLPASS=<keystore-password> node deploy.mjs
```

## Deployed

| | |
|---|---|
| Contract (Bradbury, chain 4221) | `0x203F67178a7B25803854D179d72Bf40Cfcdc2c88` |
| Explorer | https://explorer-bradbury.genlayer.com/address/0x203F67178a7B25803854D179d72Bf40Cfcdc2c88 |
| Live app | https://adebisi1111.github.io/milestone-markets/app.html |
| Landing | https://adebisi1111.github.io/milestone-markets/ |
| Repository | https://github.com/Adebisi1111/milestone-markets |

**Deployed source == published source.** `genlayer-js getContractCode` on the
address returns the contract source from the chain; its sha256 matches
`contracts/milestone_market.py` in this repo:

```
on-chain sha256: 932b4bb405a92e15
repo     sha256: 932b4bb405a92e15
```

Reads confirm live state: `getCount` = **2**, `milestone-1` **OPEN** on
`genlayerlabs/genlayer-js`, `milestone-2` **SETTLED / YES** (0.8 GEN pool), and
`contractBalance` = **0** — the payout emptied it.

The explorer path is `/address/` (verified 200); `/contract/` returns 404.

### Contract size is a deploy constraint

Bradbury rejects a contract over roughly 19.5 KB with `gas limit too high` — it
is a size ceiling, not a gas setting, and raising `gasLimit` does not help. This
was verified rather than assumed: a 20,641-byte copy of this contract fails with

```
GenLayer RPC error (eth_sendRawTransaction): [...] gas limit too high
```

while the 19,301-byte file deploys. An earlier revision of this contract grew to
20,235 bytes when the balance guard was added and would have failed to deploy for
that reason alone. The docstrings and comments are compressed to keep headroom;
the evaluator prompt and the equivalence-principle string are left intact,
because they are the judged artifact rather than prose about it.

The two-direction live proof (YES and NO) was produced on an earlier deploy,
which this one supersedes:

| Market | Criteria | Outcome | Tx |
|---|---|---|---|
| `milestone-1` | At least one pull request has been merged into this repository. | **YES** | `0xa821e44c41253231fa6d4d174bdaf1b330a2c24ec123aa582b34e55896f5369f` |
| `milestone-2` | A quantum teleportation module exists at /src/quantum.py with full unit tests. | **NO** | `0x1d29c62ce933ba1519504be57bb7523bbc891763dcc1dbded53973c35f5c425c` |

### The payout was proven with a real balance delta

Not a bookkeeping map, and not the tx status — actual `eth_getBalance` on both
sides, on this contract, with two distinct funded accounts (the deployer only
paid fees and staked the losing side, per the steward rule that the deployer must
not be a participant):

| | |
|---|---|
| staker A (main) | staked **0.3 GEN on NO** |
| staker B (throwaway `0x5e048eD4BFd5AEd9EA75a48f5abFF950E7f28dD7`) | staked **0.5 GEN on YES** |
| pool after staking | **0.8 GEN** — and `contractBalance` read **0.8 GEN**, so the value really arrived |
| consensus | round 1 `LEADER_TIMEOUT`, round 2 `VALIDATORS_TIMEOUT`, round 3 → **YES** |
| `settle` | `SETTLED` |
| `claim` by B | emitted an external message `{recipient: B, value: 0.8e18, onAcceptance: false}` |

Then, once the claim transaction reached `FINALIZED`:

```
contract  0.800000 GEN  ->  0.000000 GEN     (delta 0.800000 GEN out)
staker B  1.499777 GEN  ->  2.299777 GEN     (delta 0.800000 GEN in)
```

Both deltas are exactly the payout. The winner received real GEN.

**Timing matters when reading this.** External messages execute on
*finalization*, not on acceptance, and on Bradbury finalization took **~20–30
minutes** here — an older tx on the same contract took about 2.4 hours. A
balance check a few minutes after the claim shows **zero movement on a payout
that is working correctly**. The proof polls for `status === 7` rather than
sleeping a fixed interval.

The alternative is not to force it: `emit_transfer` takes
`on: Literal['accepted', 'finalized']` defaulting to `'finalized'`, and the
stdlib warns that value transfers on `accepted` "may lead to undesired results.
Prefer to use `finalized` (default)." The slow path is the correct one.

**Studio Next (chain 61997) is not deployed.** The `genlayer-js` build available
here exposes no `estimateTransactionFees` / `createFeesDistribution`, and a plain
`deployContract` to 61997 reverts at the consensus contract
(`0xb7278A61aa25c888815aFC32Ad3cC52fF24fE575`) because the transaction carries no
v0.6 fee distribution. That deploy has to be made from the Studio Next web UI,
which builds the fee envelope client-side.

## Launching on mainnet

`app.html` has exactly one chain-specific block. To launch:

1. set `NETWORK = "mainnet"`
2. fill in the `mainnet` entry — `chainId`, `rpcUrl`, `explorer`, `contract`

Nothing else in the file names a network, an RPC, an explorer or an address, so
those two edits are the whole change. (`index.html` is the landing page and has
no chain config at all.)

The SDK ships **no mainnet chain definition** (it exports only `localnet`,
`studionet`, `testnetAsimov`, `testnetBradbury`), so `chainFor()` builds the
target by `.extend()`-ing the Bradbury definition. `.extend()` keeps the
consensus contract and its ABI — a hand-written `{ id, rpcUrls }` literal
silently loses both, which is how the first Studio Next attempt failed.

On connect the page switches (or adds) the chain in the wallet, so a user on the
wrong network is corrected *before* they sign rather than signing a transaction
into nothing.

### Verify these before announcing

| Check | Why it matters |
|---|---|
| **The fee envelope** | The one thing that has actually blocked a deploy here. `deployContract` to Studio Next reverts at the consensus contract because the tx carries no v0.6 fee distribution, and this `genlayer-js` build exposes no `estimateTransactionFees`. Confirm the mainnet fee path **from the UI** before launch — this is the highest-risk unknown. |
| **GitHub rate limit** | `api.github.com` allows 60 requests/hour per IP unauthenticated and each `resolve` makes three, so ~20 resolves/hour per validator IP. Real volume needs a caching proxy or an authenticated mirror in front of the API. |
| **Finalization timing** | Payouts execute on finalization — measured 20 min to 2.4 h on Bradbury. If mainnet differs, `PAYOUT_POLLS` and the UI copy should follow. |

### Who pays to resolve

`resolve` is permissionless, costs the caller gas, and consensus is the expensive
part — and nobody is paid to call it. In practice the winning staker is the
natural resolver: they need the market settled to claim, so they pay the three
transactions and collect the pool. A market whose winners never act is still not
lost — `void` refunds every staker once it is 30 days past the deadline. A
production version would pay the resolver a cut of the pool.

### What was proven, and how

- **The payout moves real GEN.** Two distinct funded accounts, full lifecycle on
  the deployed contract, `eth_getBalance` on both sides: contract 0.8 → 0.0 GEN,
  winner 1.499777 → 2.299777 GEN. Both deltas exactly the payout.
- **The frontend asks the wallet to sign.** Verified with a mock EIP-1193
  provider injected before page load: `eth_sendTransaction` is requested, the
  page does not navigate away, and there is no link to a Studio deploy UI.
- **The app shows the real balance.** Connected against the live contract, the
  nav reads 29.6624 GEN from the chain and the position panel computes wallet /
  staked / claimable from on-chain positions.
- **27 direct-mode tests**, with the two fund-safety guards mutation-checked.
- **Deployed source == published source**, pinned by sha256.
- **No layout overflow or element overlap** at 1280px, checked programmatically
  rather than by eye.
