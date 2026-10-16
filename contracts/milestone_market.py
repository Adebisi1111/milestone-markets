# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
"""MilestoneMarkets — prediction markets on open-source delivery.

Users bet YES or NO on whether a named repository ships a milestone by a
deadline. There is no human judge and no oracle: `resolve()` has every
validator independently fetch the repository's commits and pull requests from
GitHub, hand them to an LLM with the milestone criteria, and agree through
comparative consensus on whether the milestone was actually met on time.

The evidence is the repository itself. Nobody — not the creator, not the
caller — can hand the validators a source of their choosing, which is the
difference between this and a market that resolves from a cited URL.

Time handling follows docs.genlayer.com "Transaction Context": the GenVM clock
is pinned to the transaction datetime and is identical across validators, so
`int(datetime.now(timezone.utc).timestamp())` is deterministic and safe for a
deadline comparison.

Payout is parimutuel; winners are paid native GEN. Paying an EOA is an EXTERNAL
message, so it goes through the EVM interface (the ghost contract) —
`gl.get_contract_at(wallet).emit_transfer()` is IC->IC only and silently moves
nothing.

Fund safety: every market can always reach a state where stakers get their GEN
back. Two paths guarantee it — `settle` voids a market whose winning side drew
no stake, and `void` releases a market the validators never managed to resolve.
Neither path can be triggered by a creator to escape a verdict they dislike.
"""

import json
from datetime import datetime, timezone

from genlayer import *

# How long after the deadline a market may sit unresolved before anyone can
# void it and refund the stakers. Without this, a market the validators never
# agree on holds every stake forever.
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


def _gh_digest(repo: str) -> str:
    """A compact, validator-stable digest of a repository's delivery evidence.

    Only stable fields are kept (short sha, author date, first message line,
    PR number/state/merged_at/title, file paths) and every list is tightly
    capped. Two reasons, both learned from live runs:

    - A raw API response differs between validators as the repo moves, and a
      varying input starves the equivalence principle of agreement.
    - Every fetch and every prompt token costs validator time. A heavy digest
      times the round out (VALIDATORS_TIMEOUT / LEADER_TIMEOUT) before consensus
      ever runs, which is why these caps are small.
    """
    lines = [f"REPOSITORY: {repo}", "COMMITS:"]
    try:
        raw = gl.nondet.web.render(
            f"https://api.github.com/repos/{repo}/commits?per_page=10", mode="text"
        )
        commits = json.loads(raw)
        for c in commits[:10]:
            sha = str(c.get("sha", ""))[:7]
            commit = c.get("commit", {}) or {}
            author = commit.get("author", {}) or {}
            date = str(author.get("date", ""))
            msg = str(commit.get("message", "")).splitlines()[0][:100] if commit.get("message") else ""
            lines.append(f"  {sha} {date} {msg}")
    except Exception:
        lines.append("  (commits could not be fetched)")

    lines.append("PULL REQUESTS:")
    try:
        raw = gl.nondet.web.render(
            f"https://api.github.com/repos/{repo}/pulls?state=all&per_page=10", mode="text"
        )
        pulls = json.loads(raw)
        for p in pulls[:10]:
            num = p.get("number", "")
            state = str(p.get("state", ""))
            merged = str(p.get("merged_at", ""))
            title = str(p.get("title", ""))[:100]
            lines.append(f"  #{num} state={state} merged_at={merged} {title}")
    except Exception:
        lines.append("  (pull requests could not be fetched)")

    # The file tree. Milestone criteria routinely name specific files or
    # features and rule 3 asks the validator to confirm they exist; without the
    # paths, a claim about a file that is NOT there cannot be disproved.
    # HEAD avoids a second request for the default branch.
    lines.append("FILES:")
    try:
        tree_raw = gl.nondet.web.render(
            f"https://api.github.com/repos/{repo}/git/trees/HEAD?recursive=1", mode="text"
        )
        for node in (json.loads(tree_raw).get("tree") or [])[:60]:
            lines.append(f"  {node.get('path', '')}")
    except Exception:
        lines.append("  (file tree could not be fetched)")

    return "\n".join(lines)


class MilestoneMarkets(gl.Contract):
    market_count: u256
    # Flat maps with string keys: nested TreeMaps and in-place dataclass
    # mutation are the two storage patterns that break consensus.
    m_creator: TreeMap[str, str]
    m_repo: TreeMap[str, str]
    m_milestone: TreeMap[str, str]
    m_deadline: TreeMap[str, u256]
    m_status: TreeMap[str, str]      # OPEN | RESOLVED | SETTLED | VOID
    m_outcome: TreeMap[str, str]     # "" | YES | NO
    m_reasoning: TreeMap[str, str]
    m_pool: TreeMap[str, u256]
    # "addr:SIDE:amt|addr:SIDE:amt|..." per market, plus "mid:addr" -> "1" claims
    m_positions: TreeMap[str, str]

    def __init__(self):
        pass

    # ------------------------------------------------------------- the request

    @gl.public.write
    def createMarket(self, repo: str, milestone: str, deadline: u256) -> str:
        """Open a market on `repo` shipping `milestone` by `deadline` (unix seconds)."""
        if not repo:
            raise gl.vm.UserError("Repository required (owner/name)")
        if "/" not in repo:
            raise gl.vm.UserError("Repository must be owner/name")
        if not milestone:
            raise gl.vm.UserError("Milestone criteria required")
        # The criteria is the text the validators judge, so it is stored
        # verbatim rather than sanitised. Views return JSON, not a delimited
        # string, so a separator character in it cannot corrupt a read.
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
        self.m_positions[mid] = ""
        return mid

    @gl.public.write.payable
    def stake(self, market_id: str, side: str) -> None:
        """Stake GEN on YES (ships on time) or NO (does not)."""
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
        pos = self.m_positions.get(market_id, "")
        entry = f"{sender}:{side}:{int(amt)}"
        self.m_positions[market_id] = (pos + "|" + entry) if pos else entry

    # -------------------------------------------------------------- the verdict

    @gl.public.write
    def resolve(self, market_id: str) -> str:
        """Judge the milestone from the repository's own evidence, by consensus.

        Every validator fetches the commits and pull requests itself and runs the
        same evaluator prompt against the milestone criteria. Comparative
        consensus reconciles their verdicts, so the outcome is the network's
        judgment of the code — not the caller's, and not a judge's.
        """
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
            data = _gh_digest(repo)
            prompt = (
                "You are an expert software engineer acting as an autonomous GenLayer validator. \n"
                "Your task is to objectively determine if an open-source development milestone "
                "has been successfully achieved.\n\n"
                "### DATA SOURCED FROM GITHUB:\n"
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
                "merge dated after the deadline is late and counts as NO.\n\n"
                "### OUTPUT FORMAT:\n"
                "You must reply in valid JSON format with exactly two keys: \"outcome\" and "
                "\"reasoning\". \n"
                "The \"outcome\" value must be strictly either \"YES\" or \"NO\".\n\n"
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
            # UNKNOWN first: a substring scan would match the "NO" inside it and
            # silently resolve an unsettled milestone against NO.
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
            f"repository milestone: {milestone}",
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
            # Validators could not agree the repository settles it. Stay OPEN so
            # it can be resolved again once the evidence is unambiguous.
            raise gl.vm.UserError("Validators could not agree on this milestone")

        self.m_status[market_id] = "RESOLVED"
        self.m_outcome[market_id] = decided
        self.m_reasoning[market_id] = reasoning
        return decided

    @gl.public.write
    def settle(self, market_id: str) -> str:
        """Lock the outcome so claims can open.

        If the winning side drew no stake there is nobody to pay, and paying
        nobody would strand the losing side's GEN in this contract forever. In
        that case the market is VOIDed instead, so every staker can take their
        own stake back.
        """
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
        """Release a market the validators never resolved, and refund the stakers.

        Only reachable once the deadline is VOID_GRACE_SECONDS past and the
        market is still OPEN. It cannot be used to escape a verdict: a resolved
        market is not OPEN, and the creator cannot call this early to dodge a
        losing outcome.
        """
        if self.m_creator.get(market_id, None) is None:
            raise gl.vm.UserError("Market not found")
        if self.m_status.get(market_id, "") != "OPEN":
            raise gl.vm.UserError("Not open")
        if _now() <= int(self.m_deadline.get(market_id, u256(0))) + VOID_GRACE_SECONDS:
            raise gl.vm.UserError("Grace period has not passed")
        self.m_status[market_id] = "VOID"
        return "VOID"

    # ---------------------------------------------------------------- the payout

    def _entries(self, market_id: str) -> list:
        out = []
        for p in self.m_positions.get(market_id, "").split("|"):
            if not p:
                continue
            pp = p.split(":")
            if len(pp) < 3:
                continue
            out.append(pp)
        return out

    def _pool_for(self, market_id: str, side: str) -> int:
        total = 0
        for pp in self._entries(market_id):
            if pp[1] == side:
                total += int(pp[2])
        return total

    def _stake_of(self, market_id: str, who: str) -> int:
        """Everything this wallet put in, on either side. Used for refunds."""
        total = 0
        for pp in self._entries(market_id):
            if pp[0] == who:
                total += int(pp[2])
        return total

    def _payout_for(self, market_id: str, who: str) -> int:
        """What this wallet can take out right now, for the market's state.

        SETTLED -> parimutuel share: winning_stake * total_pool // winning_pool.
        VOID    -> its own stake back, both sides summed.
        anything else -> nothing is claimable yet.
        """
        status = self.m_status.get(market_id, "")
        if status == "VOID":
            return self._stake_of(market_id, who)
        if status != "SETTLED":
            return 0

        outcome = self.m_outcome.get(market_id, "")
        total_pool = int(self.m_pool.get(market_id, u256(0)))
        user_stake = 0
        winning_pool = 0
        for pp in self._entries(market_id):
            if pp[1] == outcome:
                # Accumulate every entry -- a wallet may stake many times.
                winning_pool += int(pp[2])
                if pp[0] == who:
                    user_stake += int(pp[2])
        if user_stake <= 0 or winning_pool <= 0:
            return 0
        return (user_stake * total_pool) // winning_pool

    @gl.public.write
    def claim(self, market_id: str) -> u256:
        """Pay the winner their parimutuel share, or a staker their refund, once."""
        if self.m_creator.get(market_id, None) is None:
            raise gl.vm.UserError("Market not found")
        if self.m_status.get(market_id, "") not in ("SETTLED", "VOID"):
            raise gl.vm.UserError("Not settled")
        sender = gl.message.sender_address.as_hex
        key = f"{market_id}:{sender}"
        if self.m_positions.get(key, "") == "1":
            raise gl.vm.UserError("Already claimed")
        payout = self._payout_for(market_id, sender)
        if payout <= 0:
            raise gl.vm.UserError("Nothing to claim")
        # Mark before transferring; a failed external message reverts the whole call.
        self.m_positions[key] = "1"
        _Payee(gl.message.sender_address).emit_transfer(value=u256(payout))
        return u256(payout)

    # ------------------------------------------------------------------- views

    @gl.public.view
    def getMarket(self, market_id: str) -> str:
        """The whole row as JSON.

        JSON rather than a delimited string: the milestone criteria is stored
        verbatim, so a separator character inside it would shift every field of
        a delimited read and make the UI render the wrong state.
        """
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
                "yes_pool": self._pool_for(market_id, "YES"),
                "no_pool": self._pool_for(market_id, "NO"),
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
        return "1" if self.m_positions.get(f"{market_id}:{user}", "") == "1" else "0"

    @gl.public.view
    def previewPayout(self, market_id: str, user: str) -> str:
        """What this wallet can take out now: parimutuel share, or a refund."""
        return str(self._payout_for(market_id, user))

    @gl.public.view
    def getPositions(self, market_id: str) -> str:
        return self.m_positions.get(market_id, "")

    @gl.public.view
    def getStake(self, market_id: str, user: str) -> str:
        """Everything this wallet has put into the market, both sides summed."""
        return str(self._stake_of(market_id, user))

    @gl.public.view
    def now(self) -> str:
        return str(_now())
