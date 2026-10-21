"""Direct-mode tests for MilestoneMarkets.

No network, no chain: the GitHub API and the LLM are mocked, and the clock is
warped with `direct_vm.warp(...)` so deadlines can be crossed inside a test.

One environment detail matters. In direct mode a payable call does NOT credit
the value to the contract — `self.balance` stays 0 however much `stake` sends —
so the `stake` helper below funds the contract explicitly, mirroring what the
chain does when it moves the GEN. Without that, `claim`'s balance guard
(correctly) refuses every payout.

The fund-safety tests at the bottom are the ones that matter: the two ways a
market could hold staker GEN forever, the read-corruption case, and the silent
no-op on an under-funded payout.
"""

import json
from datetime import datetime, timezone

from tests.direct.conftest import to_hex


def ts(iso: str) -> int:
    return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp())


BEFORE = "2026-01-01T00:00:00Z"
DEADLINE = "2026-02-01T00:00:00Z"
AFTER = "2026-03-01T00:00:00Z"
LONG_AFTER = "2026-04-15T00:00:00Z"   # beyond deadline + 30d grace

REPO = "example/rocket"
MILESTONE = "Implement automated database backup with unit tests and merge into main"


def _mock_github(vm, commits=None, pulls=None, files=None):
    vm.mock_web(
        r".*api\.github\.com/repos/[^/]+/[^/]+/commits.*",
        {
            "status": 200,
            "body": json.dumps(
                commits
                if commits is not None
                else [
                    {
                        "sha": "a1b2c3d4e5f6",
                        "commit": {
                            "author": {"date": "2026-01-20T10:00:00Z"},
                            "message": "feat: automated database backup (#24)",
                        },
                    }
                ]
            ),
        },
    )
    vm.mock_web(
        r".*api\.github\.com/repos/[^/]+/[^/]+/pulls.*",
        {
            "status": 200,
            "body": json.dumps(
                pulls
                if pulls is not None
                else [
                    {
                        "number": 24,
                        "state": "closed",
                        "merged_at": "2026-01-20T10:00:00Z",
                        "title": "Automated database backup with unit tests",
                    }
                ]
            ),
        },
    )
    vm.mock_web(
        r".*api\.github\.com/repos/[^/]+/[^/]+/git/trees/.*",
        {
            "status": 200,
            "body": json.dumps(
                {
                    "tree": [
                        {"path": p}
                        for p in (
                            files
                            if files is not None
                            else ["src/backup.py", "tests/test_backup.py"]
                        )
                    ]
                }
            ),
        },
    )


def _verdict(vm, outcome: str, reasoning: str = "Merged in time."):
    vm.mock_llm(
        r"(?s).*autonomous GenLayer validator.*",
        json.dumps({"outcome": outcome, "reasoning": reasoning}),
    )


def row(c, mid):
    return json.loads(c.getMarket(mid))


def stake(vm, c, who, mid, side, amount):
    """Stake, then mirror on-chain value movement into the contract balance.

    Direct mode leaves `self.balance` at 0 after a payable call, so the stake is
    credited here the way the chain credits it.
    """
    vm.sender = who
    vm.value = amount
    c.stake(mid, side)
    vm.deal(c.address, int(c.contractBalance()) + amount)
    vm.value = 0


def _open(vm, c, who):
    vm.sender = who
    return c.createMarket(REPO, MILESTONE, ts(DEADLINE))


# ------------------------------------------------------------------ creation


def test_create_market(direct_vm, direct_deploy, direct_alice):
    direct_vm.warp(BEFORE)
    c = direct_deploy("contracts/milestone_market.py")
    mid = _open(direct_vm, c, direct_alice)
    assert mid == "milestone-1"

    m = row(c, mid)
    assert m["exists"] is True
    assert m["repo"] == REPO
    assert m["milestone"] == MILESTONE
    assert m["status"] == "OPEN"
    assert m["outcome"] == ""
    assert m["deadline"] == ts(DEADLINE)
    assert m["pool"] == 0
    assert c.getCount() == "1"


def test_create_requires_owner_slash_name(direct_vm, direct_deploy, direct_alice):
    direct_vm.warp(BEFORE)
    c = direct_deploy("contracts/milestone_market.py")
    direct_vm.sender = direct_alice
    with direct_vm.expect_revert("owner/name"):
        c.createMarket("justaname", MILESTONE, ts(DEADLINE))


def test_create_requires_milestone(direct_vm, direct_deploy, direct_alice):
    direct_vm.warp(BEFORE)
    c = direct_deploy("contracts/milestone_market.py")
    direct_vm.sender = direct_alice
    with direct_vm.expect_revert("Milestone criteria required"):
        c.createMarket(REPO, "", ts(DEADLINE))


def test_create_rejects_past_deadline(direct_vm, direct_deploy, direct_alice):
    direct_vm.warp(AFTER)
    c = direct_deploy("contracts/milestone_market.py")
    direct_vm.sender = direct_alice
    with direct_vm.expect_revert("Deadline must be in the future"):
        c.createMarket(REPO, MILESTONE, ts(DEADLINE))


def test_getMarket_unknown_id(direct_vm, direct_deploy):
    direct_vm.warp(BEFORE)
    c = direct_deploy("contracts/milestone_market.py")
    assert json.loads(c.getMarket("nope"))["exists"] is False


# --------------------------------------------------------------------- staking


def test_stake_yes_and_no(direct_vm, direct_deploy, direct_alice, direct_bob):
    direct_vm.warp(BEFORE)
    c = direct_deploy("contracts/milestone_market.py")
    mid = _open(direct_vm, c, direct_alice)

    stake(direct_vm, c, direct_alice, mid, "YES", 100)
    stake(direct_vm, c, direct_bob, mid, "NO", 50)

    m = row(c, mid)
    assert m["pool"] == 150
    assert m["yes_pool"] == 100
    assert m["no_pool"] == 50

    assert c.getStake(mid, to_hex(direct_alice)) == "100"
    assert c.getStake(mid, to_hex(direct_bob)) == "50"
    assert c.getStake(mid, to_hex(direct_alice)) == "100"


def test_stake_rejects_bad_side(direct_vm, direct_deploy, direct_alice):
    direct_vm.warp(BEFORE)
    c = direct_deploy("contracts/milestone_market.py")
    mid = _open(direct_vm, c, direct_alice)
    direct_vm.value = 10
    with direct_vm.expect_revert("Side must be YES or NO"):
        c.stake(mid, "MAYBE")


def test_stake_rejects_zero_value(direct_vm, direct_deploy, direct_alice):
    direct_vm.warp(BEFORE)
    c = direct_deploy("contracts/milestone_market.py")
    mid = _open(direct_vm, c, direct_alice)
    direct_vm.value = 0
    with direct_vm.expect_revert("Must send GEN"):
        c.stake(mid, "YES")


def test_stake_rejected_after_deadline(direct_vm, direct_deploy, direct_alice):
    direct_vm.warp(BEFORE)
    c = direct_deploy("contracts/milestone_market.py")
    mid = _open(direct_vm, c, direct_alice)

    direct_vm.warp(AFTER)
    direct_vm.value = 10
    with direct_vm.expect_revert("Deadline has passed"):
        c.stake(mid, "YES")


# -------------------------------------------------------------------- resolve


def test_resolve_before_deadline_reverts(direct_vm, direct_deploy, direct_alice):
    direct_vm.warp(BEFORE)
    c = direct_deploy("contracts/milestone_market.py")
    mid = _open(direct_vm, c, direct_alice)
    with direct_vm.expect_revert("deadline has not passed"):
        c.resolve(mid)


def test_resolve_yes_when_merged_before_deadline(direct_vm, direct_deploy, direct_alice):
    direct_vm.warp(BEFORE)
    c = direct_deploy("contracts/milestone_market.py")
    mid = _open(direct_vm, c, direct_alice)

    direct_vm.warp(AFTER)
    _mock_github(direct_vm)
    _verdict(direct_vm, "YES", "PR #24 merged 2026-01-20, before the deadline.")

    assert c.resolve(mid) == "YES"
    m = row(c, mid)
    assert m["status"] == "RESOLVED"
    assert m["outcome"] == "YES"
    assert "merged" in c.getReasoning(mid).lower()


def test_resolve_no_when_never_merged(direct_vm, direct_deploy, direct_alice):
    direct_vm.warp(BEFORE)
    c = direct_deploy("contracts/milestone_market.py")
    mid = _open(direct_vm, c, direct_alice)

    direct_vm.warp(AFTER)
    _mock_github(direct_vm, commits=[], pulls=[])
    _verdict(direct_vm, "NO", "No matching pull request was ever merged.")

    with direct_vm.expect_revert("No commits found before deadline"):
        c.resolve(mid)


def test_resolve_is_not_repeatable(direct_vm, direct_deploy, direct_alice):
    direct_vm.warp(BEFORE)
    c = direct_deploy("contracts/milestone_market.py")
    mid = _open(direct_vm, c, direct_alice)

    direct_vm.warp(AFTER)
    _mock_github(direct_vm)
    _verdict(direct_vm, "YES")
    c.resolve(mid)

    with direct_vm.expect_revert("Already resolved"):
        c.resolve(mid)


def test_caller_supplies_no_evidence_source(direct_vm, direct_deploy, direct_alice):
    """The caller supplies no source: the contract builds the GitHub URLs itself."""
    direct_vm.warp(BEFORE)
    c = direct_deploy("contracts/milestone_market.py")
    mid = _open(direct_vm, c, direct_alice)

    direct_vm.warp(AFTER)
    _mock_github(direct_vm)
    _verdict(direct_vm, "YES")
    c.resolve(mid)

    # If the caller could choose the source, there would be a setter.
    assert not hasattr(c, "setSource")
    assert not hasattr(c, "set_source")


# ------------------------------------------------------- BUG 3: read integrity


def test_criteria_containing_the_separator_does_not_corrupt_reads(
    direct_vm, direct_deploy, direct_alice
):
    """A `|` in the criteria must not shift the other fields.

    getMarket used to return a `|`-delimited string, so criteria containing `|`
    pushed every later field one slot along and the UI rendered the wrong state.
    """
    direct_vm.warp(BEFORE)
    c = direct_deploy("contracts/milestone_market.py")
    direct_vm.sender = direct_alice

    nasty = "Ship A | B | C, with tests | docs, merged to main"
    mid = c.createMarket(REPO, nasty, ts(DEADLINE))

    m = row(c, mid)
    assert m["milestone"] == nasty          # stored verbatim
    assert m["status"] == "OPEN"            # NOT shifted into the criteria
    assert m["repo"] == REPO
    assert m["deadline"] == ts(DEADLINE)


def test_criteria_with_separator_after_resolution(
    direct_vm, direct_deploy, direct_alice
):
    direct_vm.warp(BEFORE)
    c = direct_deploy("contracts/milestone_market.py")
    direct_vm.sender = direct_alice
    mid = c.createMarket(REPO, "Backup: nightly | hourly", ts(DEADLINE))

    direct_vm.warp(AFTER)
    _mock_github(direct_vm)
    _verdict(direct_vm, "YES", "Merged | tested")
    c.resolve(mid)

    m = row(c, mid)
    assert m["status"] == "RESOLVED"
    assert m["outcome"] == "YES"
    assert m["milestone"] == "Backup: nightly | hourly"


# ------------------------------------------------------ settle + claim (happy)


def test_claim_parimutuel(direct_vm, direct_deploy, direct_alice, direct_bob):
    direct_vm.warp(BEFORE)
    c = direct_deploy("contracts/milestone_market.py")
    mid = _open(direct_vm, c, direct_alice)
    stake(direct_vm, c, direct_alice, mid, "YES", 100)
    stake(direct_vm, c, direct_bob, mid, "NO", 50)

    direct_vm.warp(AFTER)
    _mock_github(direct_vm)
    _verdict(direct_vm, "YES")
    c.resolve(mid)
    assert c.settle(mid) == "SETTLED"

    assert c.previewPayout(mid, to_hex(direct_alice)) == "150"
    assert c.previewPayout(mid, to_hex(direct_bob)) == "0"

    direct_vm.sender = direct_alice
    assert c.claim(mid) == 150
    assert c.isClaimed(mid, to_hex(direct_alice)) == "1"

    with direct_vm.expect_revert("Already claimed"):
        c.claim(mid)


def test_loser_cannot_claim(direct_vm, direct_deploy, direct_alice, direct_bob):
    direct_vm.warp(BEFORE)
    c = direct_deploy("contracts/milestone_market.py")
    mid = _open(direct_vm, c, direct_alice)
    stake(direct_vm, c, direct_alice, mid, "YES", 100)
    stake(direct_vm, c, direct_bob, mid, "NO", 50)

    direct_vm.warp(AFTER)
    _mock_github(direct_vm)
    _verdict(direct_vm, "YES")
    c.resolve(mid)
    c.settle(mid)

    direct_vm.sender = direct_bob
    with direct_vm.expect_revert("Nothing to claim"):
        c.claim(mid)


def test_claim_requires_settlement(direct_vm, direct_deploy, direct_alice):
    direct_vm.warp(BEFORE)
    c = direct_deploy("contracts/milestone_market.py")
    mid = _open(direct_vm, c, direct_alice)
    stake(direct_vm, c, direct_alice, mid, "YES", 100)

    direct_vm.warp(AFTER)
    _mock_github(direct_vm)
    _verdict(direct_vm, "YES")
    c.resolve(mid)  # RESOLVED, not yet SETTLED

    with direct_vm.expect_revert("Not settled"):
        c.claim(mid)


# ------------------------------------- BUG 4: silent no-op on a short balance


def test_claim_refuses_and_does_not_burn_the_claim_when_balance_is_short(
    direct_vm, direct_deploy, direct_alice, direct_bob
):
    """An emit_transfer larger than the contract holds moves NOTHING.

    It returns success. So if the claim were marked first, the winner would be
    recorded as paid, receive zero, and be blocked from retrying by
    "Already claimed". The guard must refuse BEFORE marking, and the claim must
    still work once the contract can cover it.
    """
    direct_vm.warp(BEFORE)
    c = direct_deploy("contracts/milestone_market.py")
    mid = _open(direct_vm, c, direct_alice)
    stake(direct_vm, c, direct_alice, mid, "YES", 100)
    stake(direct_vm, c, direct_bob, mid, "NO", 50)

    direct_vm.warp(AFTER)
    _mock_github(direct_vm)
    _verdict(direct_vm, "YES")
    c.resolve(mid)
    c.settle(mid)

    # Drain the contract below the 150 payout.
    direct_vm.deal(c.address, 10)
    assert c.contractBalance() == "10"

    direct_vm.sender = direct_alice
    with direct_vm.expect_revert("balance is short"):
        c.claim(mid)

    # The claim must NOT have been burned.
    assert c.isClaimed(mid, to_hex(direct_alice)) == "0"

    # Refund the contract; the same claim now succeeds.
    direct_vm.deal(c.address, 150)
    assert c.claim(mid) == 150
    assert c.isClaimed(mid, to_hex(direct_alice)) == "1"


def test_contract_balance_view_tracks_stakes(
    direct_vm, direct_deploy, direct_alice, direct_bob
):
    direct_vm.warp(BEFORE)
    c = direct_deploy("contracts/milestone_market.py")
    mid = _open(direct_vm, c, direct_alice)
    assert c.contractBalance() == "0"

    stake(direct_vm, c, direct_alice, mid, "YES", 100)
    stake(direct_vm, c, direct_bob, mid, "NO", 50)
    assert c.contractBalance() == "150"
    assert c.contractBalance() == str(row(c, mid)["pool"])


# ------------------------------------------- BUG 1: no winning staker -> VOID


def test_no_winning_stake_voids_instead_of_stranding_funds(
    direct_vm, direct_deploy, direct_alice, direct_bob
):
    """Outcome YES, but only NO was backed.

    Paying nobody would hold bob's 50 GEN in the contract forever. Settling must
    VOID the market so every staker can take their own stake back.
    """
    direct_vm.warp(BEFORE)
    c = direct_deploy("contracts/milestone_market.py")
    mid = _open(direct_vm, c, direct_alice)

    # Only the losing side is backed.
    stake(direct_vm, c, direct_bob, mid, "NO", 50)

    direct_vm.warp(AFTER)
    _mock_github(direct_vm)
    _verdict(direct_vm, "YES")
    c.resolve(mid)

    assert c.settle(mid) == "VOID"
    assert row(c, mid)["status"] == "VOID"

    # Bob gets his own stake back rather than losing it to nobody.
    assert c.previewPayout(mid, to_hex(direct_bob)) == "50"
    direct_vm.sender = direct_bob
    assert c.claim(mid) == 50
    assert c.isClaimed(mid, to_hex(direct_bob)) == "1"

    with direct_vm.expect_revert("Already claimed"):
        c.claim(mid)


# ------------------------------------ BUG 2: unresolved market -> void/refund


def test_unresolved_market_can_be_voided_after_grace(
    direct_vm, direct_deploy, direct_alice, direct_bob
):
    """A market the validators never agree on must not hold GEN forever."""
    direct_vm.warp(BEFORE)
    c = direct_deploy("contracts/milestone_market.py")
    mid = _open(direct_vm, c, direct_alice)
    stake(direct_vm, c, direct_alice, mid, "YES", 100)
    stake(direct_vm, c, direct_bob, mid, "NO", 60)

    # Past the deadline but still inside the grace window: not yet voidable.
    direct_vm.warp(AFTER)
    with direct_vm.expect_revert("Grace period has not passed"):
        c.void(mid)

    direct_vm.warp(LONG_AFTER)
    assert c.void(mid) == "VOID"

    # Each side gets exactly its own stake back, not the pooled total.
    assert c.previewPayout(mid, to_hex(direct_alice)) == "100"
    assert c.previewPayout(mid, to_hex(direct_bob)) == "60"

    direct_vm.sender = direct_alice
    assert c.claim(mid) == 100
    direct_vm.sender = direct_bob
    assert c.claim(mid) == 60


def test_a_wallet_that_staked_both_sides_refunds_the_sum(
    direct_vm, direct_deploy, direct_alice
):
    direct_vm.warp(BEFORE)
    c = direct_deploy("contracts/milestone_market.py")
    mid = _open(direct_vm, c, direct_alice)
    stake(direct_vm, c, direct_alice, mid, "YES", 40)
    stake(direct_vm, c, direct_alice, mid, "NO", 10)

    direct_vm.warp(LONG_AFTER)
    c.void(mid)
    assert c.previewPayout(mid, to_hex(direct_alice)) == "50"
    assert c.claim(mid) == 50


def test_void_cannot_be_used_to_escape_a_verdict(
    direct_vm, direct_deploy, direct_alice, direct_bob
):
    """A resolved market is not OPEN, so the creator cannot dodge a loss."""
    direct_vm.warp(BEFORE)
    c = direct_deploy("contracts/milestone_market.py")
    mid = _open(direct_vm, c, direct_alice)
    stake(direct_vm, c, direct_alice, mid, "YES", 100)
    stake(direct_vm, c, direct_bob, mid, "NO", 60)

    direct_vm.warp(AFTER)
    _mock_github(direct_vm)
    _verdict(direct_vm, "NO")     # the creator's YES side loses
    c.resolve(mid)

    direct_vm.warp(LONG_AFTER)
    with direct_vm.expect_revert("Not open"):
        c.void(mid)

    # The verdict stands and the winner is paid the whole pool.
    c.settle(mid)
    assert c.previewPayout(mid, to_hex(direct_bob)) == "160"


def test_void_is_not_repeatable(direct_vm, direct_deploy, direct_alice):
    direct_vm.warp(BEFORE)
    c = direct_deploy("contracts/milestone_market.py")
    mid = _open(direct_vm, c, direct_alice)
    stake(direct_vm, c, direct_alice, mid, "YES", 10)

    direct_vm.warp(LONG_AFTER)
    c.void(mid)
    with direct_vm.expect_revert("Not open"):
        c.void(mid)


def test_preview_payout_is_zero_while_open(direct_vm, direct_deploy, direct_alice):
    direct_vm.warp(BEFORE)
    c = direct_deploy("contracts/milestone_market.py")
    mid = _open(direct_vm, c, direct_alice)
    stake(direct_vm, c, direct_alice, mid, "YES", 100)
    assert c.previewPayout(mid, to_hex(direct_alice)) == "0"


# ------------------------------------------------------------------ new: steward fixes

def test_claim_rejects_attached_gen(direct_vm, direct_deploy, direct_alice, direct_bob):
    direct_vm.warp(BEFORE)
    c = direct_deploy("contracts/milestone_market.py")
    mid = _open(direct_vm, c, direct_alice)
    stake(direct_vm, c, direct_alice, mid, "YES", 100)
    stake(direct_vm, c, direct_bob, mid, "NO", 50)

    direct_vm.warp(AFTER)
    _mock_github(direct_vm)
    _verdict(direct_vm, "YES")
    c.resolve(mid)
    c.settle(mid)

    # claim with attached GEN should revert
    direct_vm.sender = direct_alice
    direct_vm.value = 1
    with direct_vm.expect_revert("does not accept GEN"):
        c.claim(mid)
    direct_vm.value = 0


def test_fail_closed_on_missing_commits(direct_vm, direct_deploy, direct_alice):
    direct_vm.warp(BEFORE)
    c = direct_deploy("contracts/milestone_market.py")
    mid = _open(direct_vm, c, direct_alice)

    direct_vm.warp(AFTER)
    _mock_github(direct_vm, commits=[])
    _verdict(direct_vm, "NO")

    with direct_vm.expect_revert("No commits found before deadline"):
        c.resolve(mid)


def test_payout_conservation(direct_vm, direct_deploy, direct_alice, direct_bob):
    direct_vm.warp(BEFORE)
    c = direct_deploy("contracts/milestone_market.py")
    mid = _open(direct_vm, c, direct_alice)
    # 3 stakes on YES, 1 on NO
    stake(direct_vm, c, direct_alice, mid, "YES", 100)
    stake(direct_vm, c, direct_bob, mid, "YES", 200)
    # bob stakes again (same wallet, different amount)
    stake(direct_vm, c, direct_bob, mid, "NO", 50)

    direct_vm.warp(AFTER)
    _mock_github(direct_vm)
    _verdict(direct_vm, "YES")
    c.resolve(mid)
    c.settle(mid)

    # alice claims
    direct_vm.sender = direct_alice
    direct_vm.value = 0
    p1 = c.claim(mid)
    # bob claims
    direct_vm.sender = direct_bob
    direct_vm.value = 0
    p2 = c.claim(mid)

    total_paid = int(p1) + int(p2)
    m = row(c, mid)
    assert total_paid == m["pool"], f"total_paid={total_paid} != pool={m['pool']}"


# ------------------------------------------------------------------ adversarial: historical evidence

def test_late_delivery_rejected(direct_vm, direct_deploy, direct_alice):
    direct_vm.warp(BEFORE)
    c = direct_deploy("contracts/milestone_market.py")
    mid = _open(direct_vm, c, direct_alice)

    direct_vm.warp(AFTER)
    # commit dated AFTER deadline
    _mock_github(
        direct_vm,
        commits=[{
            "sha": "late123",
            "commit": {
                "author": {"date": "2026-02-15T10:00:00Z"},
                "message": "feat: late delivery",
            },
        }],
        pulls=[{
            "number": 99,
            "state": "closed",
            "merged_at": "2026-02-15T10:00:00Z",
            "title": "Late PR",
        }],
    )
    _verdict(direct_vm, "NO", "Merged after deadline.")
    assert c.resolve(mid) == "NO"


def test_github_outage_fails_closed(direct_vm, direct_deploy, direct_alice):
    direct_vm.warp(BEFORE)
    c = direct_deploy("contracts/milestone_market.py")
    mid = _open(direct_vm, c, direct_alice)

    direct_vm.warp(AFTER)
    # Mock commits to return 500 error
    direct_vm.mock_web(
        r".*api\.github\.com/repos/[^/]+/[^/]+/commits.*",
        {"status": 500, "body": "Internal Server Error"},
    )
    _verdict(direct_vm, "NO")
    with direct_vm.expect_revert("could not be fetched"):
        c.resolve(mid)


def test_malformed_commits_fails_closed(direct_vm, direct_deploy, direct_alice):
    direct_vm.warp(BEFORE)
    c = direct_deploy("contracts/milestone_market.py")
    mid = _open(direct_vm, c, direct_alice)

    direct_vm.warp(AFTER)
    direct_vm.mock_web(
        r".*api\.github\.com/repos/[^/]+/[^/]+/commits.*",
        {"status": 200, "body": "not json at all"},
    )
    direct_vm.mock_web(
        r".*api\.github\.com/repos/[^/]+/[^/]+/pulls.*",
        {"status": 200, "body": "[]"},
    )
    direct_vm.mock_web(
        r".*api\.github\.com/repos/[^/]+/[^/]+/git/trees/.*",
        {"status": 200, "body": '{"tree": []}'},
    )
    # commits mock returns non-JSON; should fail closed
    with direct_vm.expect_revert():
        c.resolve(mid)
