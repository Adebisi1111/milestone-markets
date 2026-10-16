# MilestoneMarkets

Prediction markets on **open-source delivery**.

Users bet YES or NO on whether a named repository ships a milestone by a
deadline. There is no human judge and no oracle: GenLayer's AI validators read
the repository's own commits and pull requests and decide whether the criteria
were met — then winners are paid automatically.

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
| What the validators see | whatever the creator pointed at | the repository's commits and pull requests |
| Trust assumption | the creator chose an honest source | the repository is the source |

There is no method on the contract that accepts a URL. `createMarket` takes a
repository (`owner/name`), the milestone criteria, and a deadline.

## Lifecycle

1. **`createMarket(repo, milestone, deadline)`** — open a market. `deadline` is
   unix seconds and must be in the future. No evidence URL is accepted.
2. **`stake(marketId, side)`** — send GEN on `YES` or `NO`. Staking closes when
   the deadline passes.
3. **`resolve(marketId)`** — after the deadline, every validator independently
   fetches `api.github.com/repos/<repo>/commits` and `/pulls`, runs the
   evaluator prompt below against the milestone criteria, and agrees through
   `gl.eq_principle.prompt_comparative`. If they cannot agree, the market stays
   `OPEN` rather than guessing.
4. **`settle(marketId)`** — lock the outcome.
5. **`claim(marketId)`** — the winner pulls their parimutuel share in native GEN.

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

## Tests

16 direct-mode tests, no network and no chain — the GitHub API and the LLM are
mocked and the clock is warped with `direct_vm.warp(...)` so the deadline can be
crossed inside a test.

```bash
python3 -m pytest tests/direct -q
# 16 passed
```

Covered: creation validation, staking both sides, bad side, zero value, staking
after the deadline, resolve before the deadline, resolve YES, resolve NO,
resolve is not repeatable, parimutuel payout math, loser cannot claim,
double-claim rejected, claim before settlement rejected.

## Known limitation

GitHub's unauthenticated API allows 60 requests/hour per IP. Each validator
fetches independently, so a heavily-resolved market can exhaust a validator's
budget; the digest degrades to `(commits could not be fetched)` and the verdict
falls back to whatever evidence did arrive. A production deployment would use a
token or a mirror.

## Deploy

```bash
GLPASS=<keystore-password> node deploy.mjs
```

## Deployed

| | |
|---|---|
| Contract (Bradbury, chain 4221) | `0xD5Ac66d80CaA33413502c9bb2eCc4dA9c8F8Cd2c` |
| Explorer | https://explorer-bradbury.genlayer.com/address/0xD5Ac66d80CaA33413502c9bb2eCc4dA9c8F8Cd2c |
| Deploy tx | `0x870da42a1c8aae414a1d813e61df52fb7f20460545af394b240d114ad3ed2b26` |
| Live app | https://adebisi1111.github.io/milestone-markets/ |
| Repository | https://github.com/Adebisi1111/milestone-markets |

**Deployed source == published source.** `genlayer-js getContractCode` on the
address returns the contract source from the chain; its sha256 matches
`contracts/milestone_market.py` in this repo:

```
on-chain sha256: e4786cda6c5f716b
repo     sha256: e4786cda6c5f716b
```

Reads confirm live state: `getCount` = 3, `milestone-1` RESOLVED YES,
`milestone-2` RESOLVED NO, `milestone-3` OPEN.

The explorer path is `/address/` (verified 200); `/contract/` returns 404.

Resolved on-chain, both directions, same repository — only the criteria differ:

| Market | Criteria | Outcome | Tx |
|---|---|---|---|
| `milestone-1` | At least one pull request has been merged into this repository. | **YES** | `0xa821e44c41253231fa6d4d174bdaf1b330a2c24ec123aa582b34e55896f5369f` |
| `milestone-2` | A quantum teleportation module exists at /src/quantum.py with full unit tests. | **NO** | `0x1d29c62ce933ba1519504be57bb7523bbc891763dcc1dbded53973c35f5c425c` |

**Studio Next (chain 61997) is not deployed.** The `genlayer-js` build available
here exposes no `estimateTransactionFees` / `createFeesDistribution`, and a plain
`deployContract` to 61997 reverts at the consensus contract
(`0xb7278A61aa25c888815aFC32Ad3cC52fF24fE575`) because the transaction carries no
v0.6 fee distribution. That deploy has to be made from the Studio Next web UI,
which builds the fee envelope client-side.

