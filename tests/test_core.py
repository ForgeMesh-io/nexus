import itertools

import pytest

from forgemesh.core import (AVAILABLE, BLOCKED, CHANGES_REQUESTED, CLAIMED, EXPIRED, IN_PROGRESS, MERGED,
                            READY_TO_MERGE, SUBMITTED, SYSTEM, VALIDATING, fold, parse_time)

_n = itertools.count()
SHA = "a" * 40
SHA2 = "b" * 40


def task(tid="NX-0001", risk="low", **kw):
    return {"id": tid, "swarm": "nexus", "title": "A task title", "objective": "Do the thing well",
            "type": "developer", "priority": 1, "risk": risk, "acceptance": ["tests pass"], **kw}


def ev(kind, time="2026-01-01T00:00:00Z", actor="alice", **kw):
    return {"id": f"e{next(_n)}", "kind": kind, "time": time, "actor": actor, **kw}


def base(*tasks, **policy):
    p = {"swarm": "nexus", "maintainers": ["boss"], "trusted_validators": ["trusty"], **policy}
    return [ev("policy", actor=SYSTEM, policy=p)] + [ev("task", actor=SYSTEM, task=t) for t in (tasks or [task()])]


def submit(actor="alice", sha=SHA, pr=1, t="NX-0001", time="2026-01-01T01:00:00Z", **sub):
    return ev("submit", time=time, actor=actor, task=t, submission={"pr": pr, "head_sha": sha, "author": actor, **sub})


def vote(actor, verdict="pass", sha=SHA, t="NX-0001", time="2026-01-01T02:00:00Z"):
    return ev("vote", time=time, actor=actor, task=t, verdict=verdict, sha=sha[:12], evidence="https://example.org/log")


def status(state, tid="NX-0001"):
    return state.tasks[tid].status


def last(state):
    return state.decisions[-1]


def test_happy_path_low_risk():
    s = fold(base() + [ev("claim", task="NX-0001"), submit(), vote("bob"),
                       ev("merged", actor=SYSTEM, task="NX-0001", pr=1, head_sha=SHA)])
    assert status(s) == MERGED
    assert all(d["accepted"] for d in s.decisions)
    assert s.tasks["NX-0001"].submission["audit"] == []


def test_first_claim_wins_second_is_rejected():
    s = fold(base() + [ev("claim", task="NX-0001", actor="alice"), ev("claim", task="NX-0001", actor="bob")])
    assert s.tasks["NX-0001"].claimant == "alice"
    assert not last(s)["accepted"] and "claimed by @alice" in last(s)["message"]


def test_replayed_event_is_ignored():
    claim = ev("claim", task="NX-0001")
    s = fold(base() + [claim, claim, dict(claim)])
    assert len(s.decisions) == 1


def test_lease_expires_and_task_is_reclaimable():
    s = fold(base() + [ev("claim", task="NX-0001", actor="alice"),
                       ev("claim", task="NX-0001", actor="bob", time="2026-01-02T00:00:01Z")])
    assert s.tasks["NX-0001"].claimant == "bob"
    assert s.tasks["NX-0001"].attempts[0]["outcome"] == "expired"


def test_vanished_agent_does_not_block_forever():
    s = fold(base() + [ev("claim", task="NX-0001")], until=parse_time("2026-01-03T00:00:00Z"))
    assert status(s) == EXPIRED


def test_renewal_extends_lease_and_is_bounded():
    events = base(max_renewals=1) + [ev("claim", task="NX-0001"),
                                     ev("renew", task="NX-0001", time="2026-01-01T20:00:00Z")]
    s = fold(events, until=parse_time("2026-01-02T10:00:00Z"))
    assert status(s) == IN_PROGRESS
    s = fold(events + [ev("renew", task="NX-0001", time="2026-01-01T21:00:00Z")])
    assert not last(s)["accepted"] and "maximum" in last(s)["message"]


def test_only_claimant_can_renew_or_submit():
    s = fold(base() + [ev("claim", task="NX-0001"), ev("renew", task="NX-0001", actor="mallory"),
                       submit(actor="mallory")])
    assert [d["accepted"] for d in s.decisions] == [True, False, False]


def test_clock_cannot_go_backwards():
    s = fold(base() + [ev("claim", task="NX-0001", time="2026-01-05T00:00:00Z"),
                       ev("claim", task="NX-0001", actor="bob", time="2026-01-01T00:00:00Z")])
    assert s.tasks["NX-0001"].claimant == "alice"


def test_author_cannot_validate_own_contribution():
    s = fold(base() + [ev("claim", task="NX-0001"), submit(), vote("alice")])
    assert not last(s)["accepted"] and "own contribution" in last(s)["message"]
    assert status(s) == SUBMITTED


def test_vote_must_reference_submitted_commit_and_evidence():
    s = fold(base() + [ev("claim", task="NX-0001"), submit(), vote("bob", sha=SHA2)])
    assert not last(s)["accepted"]
    s = fold(base() + [ev("claim", task="NX-0001"), submit(),
                       ev("vote", actor="bob", task="NX-0001", verdict="pass", sha=SHA[:12], evidence="")])
    assert not last(s)["accepted"]


def test_new_push_invalidates_votes():
    s = fold(base(task(risk="medium")) + [ev("claim", task="NX-0001"), submit(), vote("bob"),
                                          ev("pr_updated", actor=SYSTEM, task="NX-0001", pr=1, head_sha=SHA2),
                                          vote("carol", sha=SHA2)])
    assert status(s) == VALIDATING  # bob's vote was on the old commit


def test_medium_needs_two_independent_passes():
    s = fold(base(task(risk="medium")) + [ev("claim", task="NX-0001"), submit(), vote("bob")])
    assert status(s) == VALIDATING
    s = fold(base(task(risk="medium")) + [ev("claim", task="NX-0001"), submit(), vote("bob"), vote("carol")])
    assert status(s) == READY_TO_MERGE


def test_high_risk_needs_trusted_vote_and_maintainer_approval():
    pre = base(task(risk="high")) + [ev("claim", task="NX-0001"), submit(), vote("bob"), vote("carol")]
    assert status(fold(pre)) == VALIDATING
    with_trusted = pre + [vote("trusty")]
    assert status(fold(with_trusted)) == VALIDATING
    assert status(fold(with_trusted + [ev("approve", actor="boss", task="NX-0001", sha=SHA[:12])])) == READY_TO_MERGE


def test_non_maintainer_cannot_approve():
    s = fold(base() + [ev("claim", task="NX-0001"), submit(), ev("approve", actor="bob", task="NX-0001", sha=SHA)])
    assert not last(s)["accepted"]


def test_trusted_fail_requests_changes():
    s = fold(base() + [ev("claim", task="NX-0001"), submit(), vote("trusty", "fail")])
    assert status(s) == CHANGES_REQUESTED
    s2 = fold(base() + [ev("claim", task="NX-0001"), submit(), vote("trusty", "fail"), submit(sha=SHA2, time="2026-01-01T03:00:00Z")])
    assert status(s2) == SUBMITTED


def test_protected_path_change_requires_maintainer():
    s = fold(base() + [ev("claim", task="NX-0001"), submit(violations=["tests/acceptance/test_x.py"]), vote("bob")])
    assert status(s) == VALIDATING and "maintainer approval" in last(s)["message"]


def test_duplicate_submission_rejected():
    s = fold(base() + [ev("claim", task="NX-0001"), submit(), submit(time="2026-01-01T01:30:00Z")])
    assert not last(s)["accepted"] and "duplicate" in last(s)["message"]


def test_identical_patch_on_other_task_rejected():
    s = fold(base(task(), task("NX-0002")) + [
        ev("claim", task="NX-0001"), ev("claim", task="NX-0002", actor="bob"),
        submit(patch_id="p1"), submit(actor="bob", t="NX-0002", pr=2, sha=SHA2, patch_id="p1")])
    assert not last(s)["accepted"] and "NX-0001" in last(s)["message"]


def test_dependency_blocks_claim_until_merged():
    events = base(task(), task("NX-0002", depends_on=["NX-0001"]))
    s = fold(events + [ev("claim", task="NX-0002", actor="bob")])
    assert not last(s)["accepted"] and s.display_status(s.tasks["NX-0002"]) == BLOCKED
    done = events + [ev("claim", task="NX-0001"), submit(), vote("bob"),
                     ev("merged", actor=SYSTEM, task="NX-0001", pr=1, head_sha=SHA),
                     ev("claim", task="NX-0002", actor="bob", time="2026-01-01T03:00:00Z")]
    assert status(fold(done), "NX-0002") == CLAIMED


def test_file_overlap_prevents_concurrent_claims_unless_parallel_group():
    a, b = task(files=["src/core/*"]), task("NX-0002", files=["src/core/state.py"])
    s = fold(base(a, b) + [ev("claim", task="NX-0001"), ev("claim", task="NX-0002", actor="bob")])
    assert not last(s)["accepted"] and "overlaps" in last(s)["message"]
    a["parallel_group"] = b["parallel_group"] = "explore"
    s = fold(base(a, b) + [ev("claim", task="NX-0001"), ev("claim", task="NX-0002", actor="bob")])
    assert last(s)["accepted"]


def test_wip_limit_per_component():
    ts = [task(f"NX-000{i}", components=["core"]) for i in range(1, 4)]
    s = fold(base(*ts, wip_limit_per_component=2) + [
        ev("claim", task="NX-0001", actor="a1"), ev("claim", task="NX-0002", actor="a2"), ev("claim", task="NX-0003", actor="a3")])
    assert [d["accepted"] for d in s.decisions] == [True, True, False]


def test_per_user_claim_limit():
    ts = [task(f"NX-000{i}") for i in range(1, 4)]
    s = fold(base(*ts, max_active_claims_per_user=2) + [ev("claim", task=t["id"]) for t in ts])
    assert [d["accepted"] for d in s.decisions] == [True, True, False]


def test_kill_switch_pauses_claims():
    s = fold(base(paused=True) + [ev("claim", task="NX-0001")])
    assert not last(s)["accepted"] and "paused" in last(s)["message"]


def test_merge_without_validation_is_flagged_for_audit():
    s = fold(base() + [ev("claim", task="NX-0001"), submit(),
                       ev("merged", actor=SYSTEM, task="NX-0001", pr=1, head_sha=SHA2)])
    assert status(s) == MERGED
    assert len(s.tasks["NX-0001"].submission["audit"]) == 2


def test_only_coordinator_can_emit_system_events():
    s = fold(base() + [ev("claim", task="NX-0001"), submit(), ev("merged", actor="alice", task="NX-0001", pr=1, head_sha=SHA)])
    assert not last(s)["accepted"] and status(s) == SUBMITTED


def test_release_and_maintainer_controls():
    s = fold(base() + [ev("claim", task="NX-0001"), ev("release", task="NX-0001")])
    assert status(s) == AVAILABLE
    s = fold(base() + [ev("block", task="NX-0001", actor="boss", reason="waiting on upstream"),
                       ev("claim", task="NX-0001")])
    assert not last(s)["accepted"]
    s = fold(base() + [ev("cancel", task="NX-0001", actor="bob")])
    assert not last(s)["accepted"]


def test_policy_change_does_not_rewrite_past_decisions():
    events = base(max_active_claims_per_user=1) + [ev("claim", task="NX-0001")]
    before = fold(events).decisions
    after = fold(events + [ev("policy", actor=SYSTEM, policy={"swarm": "nexus", "maintainers": ["boss"], "paused": True})]).decisions
    assert before == after


def test_unknown_task_and_command():
    s = fold(base() + [ev("claim", task="NX-9999"), ev("invalid", task=None, line="/fm hack")])
    assert [d["accepted"] for d in s.decisions] == [False, False]


@pytest.mark.parametrize("seed", range(20))
def test_fold_is_deterministic(seed):
    import random
    rnd = random.Random(seed)
    events = base(task(), task("NX-0002"))
    for i in range(50):
        kind = rnd.choice(["claim", "renew", "release", "start"])
        events.append(ev(kind, task=rnd.choice(["NX-0001", "NX-0002"]), actor=rnd.choice(["a", "b", "c"]),
                         time=f"2026-01-01T{i // 6:02d}:{i % 6 * 10:02d}:00Z"))
    assert fold(events).to_json() == fold(list(events)).to_json()
    assert all(sum(1 for t in fold(events[:k]).tasks.values() if t.claimant) <= 2 for k in range(len(events)))
