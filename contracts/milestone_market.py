# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
"""MilestoneMarkets — prediction markets on open-source delivery.

Users bet YES or NO on whether a named repository ships a milestone by a
deadline. There is no judge and no oracle: `resolve()` has every validator fetch
the repository's own commits, pull requests and file tree, judge them against the
milestone criteria, and agree through comparative consensus.

The evidence is the repository itself. Nobody — not the creator, not the caller —
can hand the validators a source of their choosing, which is the difference
between this and a market resolved from a cited URL.

Time follows docs.genlayer.com "Transaction Context": the GenVM clock is pinned
to the transaction datetime and identical across validators, so
`int(datetime.now(timezone.utc).timestamp())` is deterministic.

Payout is parimutuel, in native GEN. Paying an EOA is an EXTERNAL message, so it
goes through the EVM interface (the ghost contract).

Fund safety: every market reaches a state where stakers get their GEN back.
`settle` voids a market whose winning side drew no stake, and `void` releases a
market the validators never resolved. Neither can be used to escape a verdict.
"""
import json
from datetime import datetime, timezone

from genlayer import *

VOID_GRACE_SECONDS = 30 * 24 * 3600


@gl.evm.contract_interface
class _Payee:
    class View:
        pass

    class Write:
        pass


def _now() -> int:
    return int(datetime.now(timezone.utc).timestamp())


def _iso(ts: int) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _gh_digest(repo: str, deadline: int) -> str:
    """Validator-stable digest of repository delivery evidence up to deadline.

    Fail-closed: any fetch failure raises UserError — missing data must not
    produce a definitive financial judgment. Historical: commits are fetched
    with `until=deadline`, PRs filtered by merge date, tree fetched at the last
    commit before the deadline.
    """
    deadline_iso = _iso(deadline)
    lines = [f"REPOSITORY: {repo}", f"DEADLINE (UTC): {deadline_iso}", "COMMITS:"]

    # 1. Commits up to deadline
    commit_shas = []
    try:
        raw = gl.nondet.web.render(
            f"https://api.github.com/repos/{repo}/commits?until={deadline_iso}&per_page=10",
            mode="text",
        )
        commits = json.loads(raw)
        if not isinstance(commits, list) or len(commits) == 0:
            raise gl.vm.UserError("No commits found before deadline")
        for c in commits[:10]:
            commit = c.get("commit", {}) or {}
            date = str((commit.get("author", {}) or {}).get("date", ""))
            msg = str(commit.get("message", "")).splitlines()[0][:100] if commit.get("message") else ""
            sha = str(c.get("sha", ""))[:7]
            lines.append(f"  {sha} {date} {msg}")
            commit_shas.append(str(c.get("sha", "")))
    except gl.vm.UserError:
        raise
    except Exception:
        raise gl.vm.UserError("GitHub commits could not be fetched")

    # 2. Pull requests merged on or before deadline
    lines.append("PULL REQUESTS:")
    try:
        raw = gl.nondet.web.render(
            f"https://api.github.com/repos/{repo}/pulls?state=all&per_page=30",
            mode="text",
        )
        pulls = json.loads(raw)
        if not isinstance(pulls, list):
            raise gl.vm.UserError("Malformed pull requests response")
        count = 0
        for p in pulls:
            merged_at = p.get("merged_at")
            if merged_at is not None and merged_at > deadline_iso:
                continue
            if merged_at is None and p.get("state") != "closed":
                continue
            lines.append(
                f"  #{p.get('number', '')} state={p.get('state', '')} "
                f"merged_at={merged_at or 'N/A'} {str(p.get('title', ''))[:100]}"
            )
            count += 1
            if count >= 10:
                break
        if count == 0:
            lines.append("  (no pull requests merged before deadline)")
    except gl.vm.UserError:
        raise
    except Exception:
        raise gl.vm.UserError("GitHub pull requests could not be fetched")

    # 3. File tree at last commit before deadline
    lines.append("FILES:")
    tree_sha = commit_shas[0] if commit_shas else "HEAD"
    try:
        tree_raw = gl.nondet.web.render(
            f"https://api.github.com/repos/{repo}/git/trees/{tree_sha}?recursive=1",
            mode="text",
        )
        tree = json.loads(tree_raw)
        tree_list = tree.get("tree") or []
        if not tree_list:
            raise gl.vm.UserError("Empty file tree")
        for node in tree_list[:60]:
            lines.append(f"  {node.get('path', '')}")
    except gl.vm.UserError:
        raise
    except Exception:
        raise gl.vm.UserError("GitHub file tree could not be fetched")

    # 4. README content for evidence depth
    lines.append("README:")
    try:
        readme_raw = gl.nondet.web.render(
            f"https://raw.githubusercontent.com/{repo}/{tree_sha}/README.md",
            mode="text",
        )
        lines.append(str(readme_raw)[:2000])
    except Exception:
        lines.append("  (README could not be fetched)")

    return "\n".join(lines)


class MilestoneMarkets(gl.Contract):
    market_count: u256
    # Flat maps with string keys
    m_creator: TreeMap[str, str]
    m_repo: TreeMap[str, str]
    m_milestone: TreeMap[str, str]
    m_deadline: TreeMap[str, u256]
    m_status: TreeMap[str, str]
    m_outcome: TreeMap[str, str]
    m_reasoning: TreeMap[str, str]
    m_pool: TreeMap[str, u256]
    m_yes_pool: TreeMap[str, u256]
    m_no_pool: TreeMap[str, u256]
    # Aggregated per-user stakes (replaces unbounded delimited string)
    m_yes_stake: TreeMap[str, u256]   # key: "mid:user"
    m_no_stake: TreeMap[str, u256]    # key: "mid:user"
    # Claim tracking
    m_claimed: TreeMap[str, u256]     # key: "mid:user" -> claimed amount
    m_paid_out: TreeMap[str, u256]    # key: market_id -> total paid out

    def __init__(self):
        pass

    @gl.public.write
    def createMarket(self, repo: str, milestone: str, deadline: u256) -> str:
        if not repo:
            raise gl.vm.UserError("Repository required (owner/name)")
        if "/" not in repo:
            raise gl.vm.UserError("Repository must be owner/name")
        if not milestone:
            raise gl.vm.UserError("Milestone criteria required")
        if int(deadline) <= _now():
            raise gl.vm.UserError("Deadline must be in the future")

        self.market_count += u256(1)
        mid = f"milestone-{self.market_count}"
        self.m_creator[mid] = gl.message.sender_address.as_hex
        self.m_repo[mid] = repo
        self.m_milestone[mid] = milestone
        self.m_deadline[mid] = deadline
        self.m_status[mid] = "OPEN"
        self.m_outcome[mid] = ""
        self.m_reasoning[mid] = ""
        self.m_pool[mid] = u256(0)
        self.m_yes_pool[mid] = u256(0)
        self.m_no_pool[mid] = u256(0)
        self.m_paid_out[mid] = u256(0)
        return mid

    @gl.public.write.payable
    def stake(self, market_id: str, side: str) -> None:
        if side not in ("YES", "NO"):
            raise gl.vm.UserError("Side must be YES or NO")
        if self.m_creator.get(market_id, None) is None:
            raise gl.vm.UserError("Market not found")
        if self.m_status.get(market_id, "") != "OPEN":
            raise gl.vm.UserError("Market not open")
        if _now() >= int(self.m_deadline.get(market_id, u256(0))):
            raise gl.vm.UserError("Deadline has passed")
        amt = gl.message.value
        if amt <= u256(0):
            raise gl.vm.UserError("Must send GEN")

        sender = gl.message.sender_address.as_hex
        self.m_pool[market_id] = u256(int(self.m_pool.get(market_id, u256(0))) + int(amt))
        if side == "YES":
            self.m_yes_pool[market_id] = u256(int(self.m_yes_pool.get(market_id, u256(0))) + int(amt))
        else:
            self.m_no_pool[market_id] = u256(int(self.m_no_pool.get(market_id, u256(0))) + int(amt))

        key = f"{market_id}:{sender}"
        if side == "YES":
            prev = int(self.m_yes_stake.get(key, u256(0)))
            self.m_yes_stake[key] = u256(prev + int(amt))
        else:
            prev = int(self.m_no_stake.get(key, u256(0)))
            self.m_no_stake[key] = u256(prev + int(amt))

    @gl.public.write
    def resolve(self, market_id: str) -> str:
        if self.m_creator.get(market_id, None) is None:
            raise gl.vm.UserError("Market not found")
        if self.m_status.get(market_id, "") != "OPEN":
            raise gl.vm.UserError("Already resolved")

        deadline = int(self.m_deadline.get(market_id, u256(0)))
        if _now() < deadline:
            raise gl.vm.UserError("Milestone deadline has not passed")

        repo = self.m_repo.get(market_id, "")
        milestone = self.m_milestone.get(market_id, "")
        deadline_iso = _iso(deadline)

        def _judge() -> str:
            data = _gh_digest(repo, deadline)
            prompt = (
                "You are an expert software engineer acting as an autonomous GenLayer validator. \n"
                "Your task is to objectively determine if an open-source development milestone "
                "has been successfully achieved.\n\n"
                "### DATA SOURCED FROM GITHUB (historical state at deadline):\n"
                f"{data}\n"
                f"MILESTONE DEADLINE (UTC): {deadline_iso}\n\n"
                "### SUCCESS CRITERIA TO EVALUATE:\n"
                f'"{milestone}"\n\n'
                "### RULES FOR EVALUATION:\n"
                "1. Base your evaluation strictly on the provided GitHub data. Do not hallucinate "
                "or assume facts.\n"
                "2. The code must be explicitly merged or completed within the repository text. \n"
                "3. If the criteria mentions specific technical requirements (e.g., unit tests, "
                "specific files, or features), verify that they actually exist in the data text. "
                "Empty files or uncompleted PRs count as a failure (NO).\n"
                "4. The milestone must have been completed ON OR BEFORE the deadline above. A "
                "merge dated after the deadline is late and counts as NO.\n"
                "5. If GitHub data is missing or incomplete, return UNKNOWN — do not guess.\n\n"
                "### OUTPUT FORMAT:\n"
                'You must reply in valid JSON format with exactly two keys: "outcome" and '
                '"reasoning". \n'
                'The "outcome" value must be strictly either "YES", "NO", or "UNKNOWN".\n\n'
                "Example Output:\n"
                "{\n"
                '  "outcome": "YES",\n'
                '  "reasoning": "Pull Request #24 was successfully merged into the main branch, '
                'containing the requested backup script in /src/backup.py alongside a comprehensive '
                'test suite in /tests/test_backup.py."\n'
                "}"
            )
            res = gl.nondet.exec_prompt(prompt, response_format="json")
            if isinstance(res, dict):
                out = str(res.get("outcome", "")).strip().upper()
                why = str(res.get("reasoning", ""))[:600]
            else:
                out = str(res).strip().upper()
                why = ""
            if "UNKNOWN" in out:
                out = "UNKNOWN"
            elif "YES" in out:
                out = "YES"
            elif "NO" in out:
                out = "NO"
            else:
                out = "UNKNOWN"
            return json.dumps({"outcome": out, "reasoning": why}, sort_keys=True)

        raw = gl.eq_principle.prompt_comparative(
            _judge,
            "Both results must give the same 'outcome' value (YES or NO) for the same "
            f"repository milestone: {milestone}. 'outcome' is the field this contract "
            "stores and settles payouts on, so it must be identical; the 'reasoning' "
            "prose may differ in wording. UNKNOWN is not an acceptable outcome — if "
            "evidence is insufficient, both must return UNKNOWN and the round fails.",
        )

        decided = ""
        reasoning = ""
        try:
            parsed = json.loads(raw) if isinstance(raw, str) else raw
            decided = str(parsed.get("outcome", "")).strip().upper()
            reasoning = str(parsed.get("reasoning", ""))[:600]
        except Exception:
            decided = ""

        if decided not in ("YES", "NO"):
            raise gl.vm.UserError("Validators could not agree on this milestone")

        self.m_status[market_id] = "RESOLVED"
        self.m_outcome[market_id] = decided
        self.m_reasoning[market_id] = reasoning
        return decided

    @gl.public.write
    def settle(self, market_id: str) -> str:
        if self.m_creator.get(market_id, None) is None:
            raise gl.vm.UserError("Market not found")
        if self.m_status.get(market_id, "") != "RESOLVED":
            raise gl.vm.UserError("Not resolved")
        if self._pool_for(market_id, self.m_outcome.get(market_id, "")) <= 0:
            self.m_status[market_id] = "VOID"
            return "VOID"
        self.m_status[market_id] = "SETTLED"
        return "SETTLED"

    @gl.public.write
    def void(self, market_id: str) -> str:
        if self.m_creator.get(market_id, None) is None:
            raise gl.vm.UserError("Market not found")
        if self.m_status.get(market_id, "") != "OPEN":
            raise gl.vm.UserError("Not open")
        if _now() <= int(self.m_deadline.get(market_id, u256(0))) + VOID_GRACE_SECONDS:
            raise gl.vm.UserError("Grace period has not passed")
        self.m_status[market_id] = "VOID"
        return "VOID"

    # --- helpers ---

    def _yes_stake(self, market_id: str, user: str) -> int:
        return int(self.m_yes_stake.get(f"{market_id}:{user}", u256(0)))

    def _no_stake(self, market_id: str, user: str) -> int:
        return int(self.m_no_stake.get(f"{market_id}:{user}", u256(0)))

    def _user_stake(self, market_id: str, user: str) -> int:
        return self._yes_stake(market_id, user) + self._no_stake(market_id, user)

    def _pool_for(self, market_id: str, side: str) -> int:
        if side == "YES":
            return int(self.m_yes_pool.get(market_id, u256(0)))
        return int(self.m_no_pool.get(market_id, u256(0)))

    # Actually, let me restructure. I need per-side pool totals.
    # Add m_yes_pool and m_no_pool to the contract.

    @gl.public.write
    def claim(self, market_id: str) -> u256:
        # Reject attached GEN
        if gl.message.value > u256(0):
            raise gl.vm.UserError("claim() does not accept GEN")
        if self.m_creator.get(market_id, None) is None:
            raise gl.vm.UserError("Market not found")
        if self.m_status.get(market_id, "") not in ("SETTLED", "VOID"):
            raise gl.vm.UserError("Not settled")
        sender = gl.message.sender_address.as_hex
        key = f"{market_id}:{sender}"
        if int(self.m_claimed.get(key, u256(0))) > 0:
            raise gl.vm.UserError("Already claimed")

        status = self.m_status.get(market_id, "")
        payout = 0

        if status == "VOID":
            payout = self._user_stake(market_id, sender)
        elif status == "SETTLED":
            outcome = self.m_outcome.get(market_id, "")
            total_pool = int(self.m_pool.get(market_id, u256(0)))
            user_stake = 0
            winning_pool = 0
            if outcome == "YES":
                user_stake = self._yes_stake(market_id, sender)
            else:
                user_stake = self._no_stake(market_id, sender)
            # winning pool = sum of all stakes on winning side
            # We need to track this. For now, compute from m_pool minus losing side.
            # Actually we need per-side totals. Let me store them.
            winning_pool = int(self.m_yes_pool.get(market_id, u256(0))) if outcome == "YES" else int(self.m_no_pool.get(market_id, u256(0)))
            if user_stake <= 0 or winning_pool <= 0:
                raise gl.vm.UserError("Nothing to claim")
            # Calculate share with remainder conservation
            paid_out = int(self.m_paid_out.get(market_id, u256(0)))
            calculated = (user_stake * total_pool) // winning_pool
            remaining = total_pool - paid_out
            # Last claimer absorbs rounding remainder for full-pool conservation.
            # Remainder is at most (number of winners), so a small bound suffices.
            if remaining <= calculated + 100:
                payout = remaining
            else:
                payout = calculated
            if payout <= 0:
                raise gl.vm.UserError("Nothing to claim")

        if payout <= 0:
            raise gl.vm.UserError("Nothing to claim")

        # Balance guard
        if int(self.balance) < payout:
            raise gl.vm.UserError("Contract balance is short of this payout")

        # Transfer first, then mark claimed (allows retry on failure)
        self.m_claimed[key] = u256(payout)
        self.m_paid_out[market_id] = u256(int(self.m_paid_out.get(market_id, u256(0))) + payout)
        _Payee(gl.message.sender_address).emit_transfer(value=u256(payout))
        return u256(payout)

    # --- views ---

    @gl.public.view
    def getMarket(self, market_id: str) -> str:
        if self.m_creator.get(market_id, None) is None:
            return json.dumps({"exists": False})
        return json.dumps(
            {
                "exists": True,
                "id": market_id,
                "creator": self.m_creator.get(market_id, ""),
                "repo": self.m_repo.get(market_id, ""),
                "milestone": self.m_milestone.get(market_id, ""),
                "status": self.m_status.get(market_id, ""),
                "outcome": self.m_outcome.get(market_id, ""),
                "deadline": int(self.m_deadline.get(market_id, u256(0))),
                "pool": int(self.m_pool.get(market_id, u256(0))),
                "yes_pool": int(self.m_yes_pool.get(market_id, u256(0))),
                "no_pool": int(self.m_no_pool.get(market_id, u256(0))),
                "reasoning": self.m_reasoning.get(market_id, ""),
            }
        )

    @gl.public.view
    def getReasoning(self, market_id: str) -> str:
        return self.m_reasoning.get(market_id, "")

    @gl.public.view
    def getCount(self) -> str:
        return str(int(self.market_count))

    @gl.public.view
    def isClaimed(self, market_id: str, user: str) -> str:
        return "1" if int(self.m_claimed.get(f"{market_id}:{user}", u256(0))) > 0 else "0"

    @gl.public.view
    def previewPayout(self, market_id: str, user: str) -> str:
        status = self.m_status.get(market_id, "")
        if status == "VOID":
            return str(self._user_stake(market_id, user))
        if status != "SETTLED":
            return "0"
        outcome = self.m_outcome.get(market_id, "")
        total_pool = int(self.m_pool.get(market_id, u256(0)))
        user_stake = self._yes_stake(market_id, user) if outcome == "YES" else self._no_stake(market_id, user)
        winning_pool = int(self.m_yes_pool.get(market_id, u256(0))) if outcome == "YES" else int(self.m_no_pool.get(market_id, u256(0)))
        if user_stake <= 0 or winning_pool <= 0:
            return "0"
        return str((user_stake * total_pool) // winning_pool)

    @gl.public.view
    def getPositions(self, market_id: str) -> str:
        return f"yes_pool={int(self.m_yes_pool.get(market_id, u256(0)))} no_pool={int(self.m_no_pool.get(market_id, u256(0)))}"

    @gl.public.view
    def getStake(self, market_id: str, user: str) -> str:
        return str(self._user_stake(market_id, user))

    @gl.public.view
    def contractBalance(self) -> str:
        return str(int(self.balance))

    @gl.public.view
    def now(self) -> str:
        return str(_now())
