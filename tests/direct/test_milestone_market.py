"""Direct-mode tests for MilestoneMarkets.

No network, no chain: the GitHub API and the LLM are mocked, and the clock is
warped with `direct_vm.warp(...)` so the milestone deadline can be crossed
inside a test.
"""

import json
from datetime import datetime, timezone

from tests.direct.conftest import to_hex


def ts(iso: str) -> int:
    return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp())


BEFORE = "2026-01-01T00:00:00Z"
DEADLINE = "2026-02-01T00:00:00Z"
AFTER = "2026-03-01T00:00:00Z"

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
                {"tree": [{"path": p} for p in (files if files is not None else ["src/backup.py", "tests/test_backup.py"])]}
            ),
        },
    )


def _verdict(vm, outcome: str, reasoning: str = "Merged in time."):
    vm.mock_llm(
        r"(?s).*autonomous GenLayer validator.*",
        json.dumps({"outcome": outcome, "reasoning": reasoning}),
    )


# ------------------------------------------------------------------ creation


def test_create_market(direct_vm, direct_deploy, direct_alice):
    direct_vm.warp(BEFORE)
    c = direct_deploy("contracts/milestone_market.py")
    direct_vm.sender = direct_alice

    mid = c.createMarket(REPO, MILESTONE, ts(DEADLINE))
    assert mid == "milestone-1"

    row = c.getMarket(mid).split("|")
    assert row[0] == REPO
    assert row[1] == MILESTONE
    assert row[2] == "OPEN"
    assert row[3] == ""
    assert row[4] == str(ts(DEADLINE))
    assert row[5] == "0"
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


# --------------------------------------------------------------------- staking


def test_stake_yes_and_no(direct_vm, direct_deploy, direct_alice, direct_bob):
    direct_vm.warp(BEFORE)
    c = direct_deploy("contracts/milestone_market.py")
    direct_vm.sender = direct_alice
    mid = c.createMarket(REPO, MILESTONE, ts(DEADLINE))

    direct_vm.sender = direct_alice
    direct_vm.value = 100
    c.stake(mid, "YES")

    direct_vm.sender = direct_bob
    direct_vm.value = 50
    c.stake(mid, "NO")

    row = c.getMarket(mid).split("|")
    assert row[5] == "150"  # total pool

    pos = c.getPositions(mid)
    assert f"{to_hex(direct_alice)}:YES:100" in pos
    assert f"{to_hex(direct_bob)}:NO:50" in pos


def test_stake_rejects_bad_side(direct_vm, direct_deploy, direct_alice):
    direct_vm.warp(BEFORE)
    c = direct_deploy("contracts/milestone_market.py")
    direct_vm.sender = direct_alice
    mid = c.createMarket(REPO, MILESTONE, ts(DEADLINE))
    direct_vm.value = 10
    with direct_vm.expect_revert("Side must be YES or NO"):
        c.stake(mid, "MAYBE")


def test_stake_rejects_zero_value(direct_vm, direct_deploy, direct_alice):
    direct_vm.warp(BEFORE)
    c = direct_deploy("contracts/milestone_market.py")
    direct_vm.sender = direct_alice
    mid = c.createMarket(REPO, MILESTONE, ts(DEADLINE))
    direct_vm.value = 0
    with direct_vm.expect_revert("Must send GEN"):
        c.stake(mid, "YES")


def test_stake_rejected_after_deadline(direct_vm, direct_deploy, direct_alice):
    direct_vm.warp(BEFORE)
    c = direct_deploy("contracts/milestone_market.py")
    direct_vm.sender = direct_alice
    mid = c.createMarket(REPO, MILESTONE, ts(DEADLINE))

    direct_vm.warp(AFTER)
    direct_vm.value = 10
    with direct_vm.expect_revert("Deadline has passed"):
        c.stake(mid, "YES")


# -------------------------------------------------------------------- resolve


def test_resolve_before_deadline_reverts(direct_vm, direct_deploy, direct_alice):
    direct_vm.warp(BEFORE)
    c = direct_deploy("contracts/milestone_market.py")
    direct_vm.sender = direct_alice
    mid = c.createMarket(REPO, MILESTONE, ts(DEADLINE))
    with direct_vm.expect_revert("deadline has not passed"):
        c.resolve(mid)


def test_resolve_yes_when_merged_before_deadline(direct_vm, direct_deploy, direct_alice):
    direct_vm.warp(BEFORE)
    c = direct_deploy("contracts/milestone_market.py")
    direct_vm.sender = direct_alice
    mid = c.createMarket(REPO, MILESTONE, ts(DEADLINE))

    direct_vm.warp(AFTER)
    _mock_github(direct_vm)
    _verdict(direct_vm, "YES", "PR #24 merged 2026-01-20, before the deadline.")

    assert c.resolve(mid) == "YES"
    row = c.getMarket(mid).split("|")
    assert row[2] == "RESOLVED"
    assert row[3] == "YES"
    assert "merged" in c.getReasoning(mid).lower()


def test_resolve_no_when_never_merged(direct_vm, direct_deploy, direct_alice):
    direct_vm.warp(BEFORE)
    c = direct_deploy("contracts/milestone_market.py")
    direct_vm.sender = direct_alice
    mid = c.createMarket(REPO, MILESTONE, ts(DEADLINE))

    direct_vm.warp(AFTER)
    _mock_github(direct_vm, commits=[], pulls=[])
    _verdict(direct_vm, "NO", "No matching pull request was ever merged.")

    assert c.resolve(mid) == "NO"
    assert c.getMarket(mid).split("|")[3] == "NO"


def test_resolve_is_not_repeatable(direct_vm, direct_deploy, direct_alice):
    direct_vm.warp(BEFORE)
    c = direct_deploy("contracts/milestone_market.py")
    direct_vm.sender = direct_alice
    mid = c.createMarket(REPO, MILESTONE, ts(DEADLINE))

    direct_vm.warp(AFTER)
    _mock_github(direct_vm)
    _verdict(direct_vm, "YES")
    c.resolve(mid)

    with direct_vm.expect_revert("Already resolved"):
        c.resolve(mid)


def test_resolve_only_the_repo_is_the_evidence(direct_vm, direct_deploy, direct_alice):
    """The caller supplies no source: the contract builds the GitHub URLs itself."""
    direct_vm.warp(BEFORE)
    c = direct_deploy("contracts/milestone_market.py")
    direct_vm.sender = direct_alice
    mid = c.createMarket(REPO, MILESTONE, ts(DEADLINE))

    direct_vm.warp(AFTER)
    _mock_github(direct_vm)
    _verdict(direct_vm, "YES")
    c.resolve(mid)

    # If the caller could choose the source, there would be a setter. There is
    # no method on this contract that accepts a URL.
    assert not hasattr(c, "setSource")
    assert not hasattr(c, "set_source")


# --------------------------------------------------------------- settle + claim


def _resolved_market(vm, c, outcome="YES"):
    vm.warp(BEFORE)
    mid = c.createMarket(REPO, MILESTONE, ts(DEADLINE))
    vm.warp(AFTER)
    _mock_github(vm)
    _verdict(vm, outcome)
    c.resolve(mid)
    c.settle(mid)
    return mid


def test_claim_parimutuel(direct_vm, direct_deploy, direct_alice, direct_bob):
    direct_vm.warp(BEFORE)
    c = direct_deploy("contracts/milestone_market.py")
    direct_vm.sender = direct_alice
    mid = c.createMarket(REPO, MILESTONE, ts(DEADLINE))

    # YES 100 (alice), NO 50 (bob) -> total 150
    direct_vm.sender = direct_alice
    direct_vm.value = 100
    c.stake(mid, "YES")
    direct_vm.sender = direct_bob
    direct_vm.value = 50
    c.stake(mid, "NO")

    direct_vm.warp(AFTER)
    _mock_github(direct_vm)
    _verdict(direct_vm, "YES")
    c.resolve(mid)
    c.settle(mid)

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
    direct_vm.sender = direct_alice
    mid = c.createMarket(REPO, MILESTONE, ts(DEADLINE))

    direct_vm.sender = direct_alice
    direct_vm.value = 100
    c.stake(mid, "YES")
    direct_vm.sender = direct_bob
    direct_vm.value = 50
    c.stake(mid, "NO")

    direct_vm.warp(AFTER)
    _mock_github(direct_vm)
    _verdict(direct_vm, "YES")
    c.resolve(mid)
    c.settle(mid)

    direct_vm.sender = direct_bob
    with direct_vm.expect_revert("No winning stake"):
        c.claim(mid)


def test_claim_requires_settlement(direct_vm, direct_deploy, direct_alice):
    direct_vm.warp(BEFORE)
    c = direct_deploy("contracts/milestone_market.py")
    direct_vm.sender = direct_alice
    mid = c.createMarket(REPO, MILESTONE, ts(DEADLINE))

    direct_vm.value = 100
    c.stake(mid, "YES")

    direct_vm.warp(AFTER)
    _mock_github(direct_vm)
    _verdict(direct_vm, "YES")
    c.resolve(mid)  # RESOLVED, not yet SETTLED

    with direct_vm.expect_revert("Not settled"):
        c.claim(mid)
