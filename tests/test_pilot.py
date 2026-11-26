import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from forgemesh import pilot


BASE = "b" * 40
REPORT = "The recipe omits the final step."


@pytest.fixture
def workspace(tmp_path):
    now = [1_000]
    path = tmp_path / "pilot.db"
    ledger = pilot.Pilot(path, clock=lambda: now[0])
    ledger.initialize("example/project", active_limit=2, lease_seconds=10)
    tokens = {
        "writer": ledger.enroll("writer", "alice", "contributor"),
        "peer": ledger.enroll("peer", "bob", "contributor"),
        "reviewer": ledger.enroll("reviewer", "carol", "reviewer"),
        "alias": ledger.enroll("alias", "alice", "reviewer"),
        "maintainer": ledger.enroll("maintainer", "dana", "maintainer"),
        "publisher": ledger.enroll("publisher", "worker", "publisher"),
    }
    ledger.add_task("guide", 10, BASE, "Check the recipe")
    return ledger, path, tokens, now


def race(*operations):
    gate = Barrier(len(operations))

    def run(operation):
        gate.wait(timeout=5)
        try:
            return operation()
        except pilot.PilotError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=len(operations)) as pool:
        return list(pool.map(run, operations))


def submit(ledger, token, task="guide", report=REPORT):
    return ledger.submit(token, task, ledger.claim(token, task), report)


def test_explicit_opt_in_and_discovery_returns_pinned_work(workspace, tmp_path):
    ledger, _, tokens, _ = workspace
    with pytest.raises(pilot.PilotError, match="not_initialized"):
        pilot.Pilot(tmp_path / "missing.db").discover(tokens["writer"])
    assert not (tmp_path / "missing.db").exists()
    with pytest.raises(pilot.PilotError, match="unauthorized"):
        ledger.discover("forged")
    assert ledger.discover(tokens["writer"]) == {
        "repository": "example/project", "tasks": [
            {"id": "guide", "issue": 10, "base": BASE, "title": "Check the recipe"},
        ],
    }
    assert ledger.discover(tokens["reviewer"])["tasks"] == []


def test_only_one_concurrent_claim_wins(workspace):
    ledger, path, tokens, now = workspace
    a, b = race(*(lambda name=name: pilot.Pilot(path, clock=lambda: now[0])
                  .claim(tokens[name], "guide") for name in ("writer", "peer")))
    assert [a, b].count("busy") == 1
    assert ledger.discover(tokens["writer"])["tasks"] == []
    assert [row["event"] for row in ledger.audit()].count("claimed") == 1


def test_concurrent_different_tasks_preserve_last_slot(workspace):
    ledger, _, tokens, _ = workspace
    third = ledger.enroll("third", "eve", "contributor")
    ledger.add_task("other", 11, BASE, "Other work")
    ledger.add_task("third", 12, BASE, "More work")
    ledger.claim(tokens["writer"], "guide")
    result = race(lambda: ledger.claim(tokens["peer"], "other"),
                  lambda: ledger.claim(third, "third"))
    assert result.count("capacity") == 1
    assert len([row for row in ledger.audit() if row["event"] == "claimed"]) == 2


def test_expired_claim_is_fenced_even_if_same_owner_reacquires(workspace):
    ledger, _, tokens, now = workspace
    writer = tokens["writer"]
    first = ledger.claim(writer, "guide")
    assert ledger.claim(writer, "guide") == first
    now[0] += 10
    second = ledger.claim(writer, "guide")
    assert second != first
    with pytest.raises(pilot.PilotError, match="stale_lease"):
        ledger.submit(writer, "guide", first, REPORT)
    assert ledger.submit(writer, "guide", second, REPORT) == (
        "88df0ca322bc605a56e7a2078f1ba120b2ab5f7f0ae53a8ae297667d1a87b9da"
    )


def test_submit_retry_is_bound_to_exact_content_and_claim(workspace):
    ledger, _, tokens, now = workspace
    lease = ledger.claim(tokens["writer"], "guide")
    digest = ledger.submit(tokens["writer"], "guide", lease, REPORT)
    now[0] += 10
    assert ledger.submit(tokens["writer"], "guide", lease, REPORT) == digest
    with pytest.raises(pilot.PilotError, match="conflict"):
        ledger.submit(tokens["writer"], "guide", lease, REPORT + "!")
    with pytest.raises(pilot.PilotError, match="stale_lease"):
        ledger.submit(tokens["peer"], "guide", lease, REPORT)
    assert [row["event"] for row in ledger.audit()].count("submitted") == 1


def test_independent_review_is_exact_and_final(workspace):
    ledger, _, tokens, _ = workspace
    digest = submit(ledger, tokens["writer"])
    assert ledger.discover(tokens["reviewer"])["tasks"][0]["report"] == REPORT
    assert ledger.discover(tokens["alias"])["tasks"] == []
    with pytest.raises(pilot.PilotError, match="independence"):
        ledger.review(tokens["alias"], "guide", digest, "pass", "Checked")
    with pytest.raises(pilot.PilotError, match="stale_digest"):
        ledger.review(tokens["reviewer"], "guide", "0" * 64, "pass", "Checked")
    reviewer = tokens["reviewer"]
    assert ledger.review(reviewer, "guide", digest, "reject", "Missing evidence") == "rejected"
    assert ledger.review(reviewer, "guide", digest, "reject", "Missing evidence") == "rejected"
    with pytest.raises(pilot.PilotError, match="conflict"):
        ledger.review(reviewer, "guide", digest, "pass", "Checked")


def test_revocation_releases_lease_and_stop_survives_restart(workspace):
    ledger, path, tokens, _ = workspace
    ledger.claim(tokens["writer"], "guide")
    ledger.revoke(tokens["maintainer"], "writer")
    with pytest.raises(pilot.PilotError, match="unauthorized"):
        ledger.claim(tokens["writer"], "guide")
    ledger.claim(tokens["peer"], "guide")
    ledger.stop(tokens["maintainer"])
    reopened = pilot.Pilot(path)
    with pytest.raises(pilot.PilotError, match="stopped"):
        reopened.claim(tokens["peer"], "guide")
    assert [row["event"] for row in reopened.audit()][-3:] == ["revoked", "claimed", "stopped"]
    assert all(token.encode() not in path.read_bytes() for token in tokens.values())


def test_invalid_input_and_failed_transaction_leave_no_audit(workspace):
    ledger, path, tokens, _ = workspace
    lease = ledger.claim(tokens["writer"], "guide")
    with pytest.raises(pilot.PilotError, match="invalid_input"):
        ledger.submit(tokens["writer"], "guide", lease, "ø" * 4097)
    with pytest.raises(pilot.PilotError, match="invalid_input"):
        ledger.add_task("not-a-revision", 11, "main", "Bad task")
    with sqlite3.connect(path) as db:
        db.executescript("""CREATE TRIGGER fail_audit BEFORE INSERT ON audit
                             WHEN NEW.event = 'submitted' BEGIN
                             SELECT RAISE(ABORT, 'test failure'); END;""")
    with pytest.raises(sqlite3.IntegrityError):
        ledger.submit(tokens["writer"], "guide", lease, REPORT)
    assert ledger.audit()[-1]["event"] == "claimed"
    assert ledger.discover(tokens["reviewer"])["tasks"] == []


def test_catalog_and_owner_caps_do_not_allow_alias_bypass(workspace):
    ledger, _, tokens, _ = workspace
    alias = ledger.enroll("writer-alias", "alice", "contributor")
    for n in range(1, 32):
        ledger.add_task(f"task-{n}", 100 + n, BASE, "More work")
    with pytest.raises(pilot.PilotError, match="capacity"):
        ledger.add_task("overflow", 200, BASE, "Over capacity")
    ledger.claim(tokens["writer"], "guide")
    with pytest.raises(pilot.PilotError, match="capacity"):
        ledger.claim(alias, "task-1")


def test_lease_attempts_are_bounded_for_a_perpetually_unfinished_task(workspace):
    ledger, _, tokens, now = workspace
    for _ in range(8):
        ledger.claim(tokens["writer"], "guide")
        now[0] += 10
    assert ledger.discover(tokens["peer"])["tasks"] == []
    with pytest.raises(pilot.PilotError, match="attempt_limit"):
        ledger.claim(tokens["peer"], "guide")


def validate(ledger, tokens, task="guide", report=REPORT, verdict="pass"):
    digest = submit(ledger, tokens["writer"], task, report)
    ledger.review(tokens["reviewer"], task, digest, verdict, "Checked against the pinned revision")
    return digest


def test_last_publication_quota_unit_is_atomic(workspace):
    ledger, _, tokens, _ = workspace
    ledger.add_task("other", 11, BASE, "Other work")
    first = validate(ledger, tokens)
    second = validate(ledger, tokens, "other", "A different report")
    result = race(lambda: ledger.authorize(tokens["maintainer"], "guide", first),
                  lambda: ledger.authorize(tokens["maintainer"], "other", second))
    assert result.count("publication_quota") == 1
    assert [row["event"] for row in ledger.audit()].count("authorized") == 1


def test_unreviewed_rejected_and_wrong_role_cannot_authorize(workspace):
    ledger, _, tokens, _ = workspace
    digest = validate(ledger, tokens, verdict="reject")
    with pytest.raises(pilot.PilotError, match="not_validated"):
        ledger.authorize(tokens["maintainer"], "guide", digest)
    with pytest.raises(pilot.PilotError, match="unauthorized"):
        ledger.authorize(tokens["writer"], "guide", digest)
    assert ledger.begin_dispatch(tokens["publisher"], "guide", BASE) is None


@pytest.mark.parametrize("action", ["stop", "revoke", "stale_base"])
def test_dispatch_rechecks_stop_revocation_and_base(workspace, action):
    ledger, _, tokens, _ = workspace
    digest = validate(ledger, tokens)
    intent = ledger.authorize(tokens["maintainer"], "guide", digest)
    assert ledger.authorize(tokens["maintainer"], "guide", digest) == intent
    if action == "stop":
        ledger.stop(tokens["maintainer"])
    if action == "revoke":
        ledger.revoke(tokens["maintainer"], "reviewer")
    with pytest.raises(pilot.PilotError, match={"stop": "stopped", "revoke": "withdrawn",
                                              "stale_base": "stale_base"}[action]):
        ledger.begin_dispatch(tokens["publisher"], "guide", "a" * 40 if action == "stale_base" else BASE)
    assert "dispatch_started" not in [row["event"] for row in ledger.audit()]


def test_reopening_after_dispatch_cannot_regrant_send_and_records_receipt(workspace):
    ledger, path, tokens, now = workspace
    digest = validate(ledger, tokens)
    marker = ledger.authorize(tokens["maintainer"], "guide", digest)
    publisher = tokens["publisher"]
    a, b = race(lambda: ledger.begin_dispatch(publisher, "guide", BASE),
                lambda: ledger.begin_dispatch(publisher, "guide", BASE))
    assert [a, b].count(None) == 1
    assert next(result for result in (a, b) if result) == {
        "repository": "example/project", "issue": 10, "base": BASE, "marker": marker,
        "digest": digest, "report": REPORT,
    }
    reopened = pilot.Pilot(path, clock=lambda: now[0])
    assert reopened.begin_dispatch(publisher, "guide", BASE) is None
    with pytest.raises(pilot.PilotError, match="unauthorized"):
        reopened.record_publication(tokens["writer"], marker, 42)
    reopened.stop(tokens["maintainer"])
    assert reopened.record_publication(publisher, marker, 42) == 42
    assert reopened.record_publication(publisher, marker, 42) == 42
    with pytest.raises(pilot.PilotError, match="conflict"):
        reopened.record_publication(publisher, marker, 43)
    assert [entry["event"] for entry in reopened.audit()].count("published") == 1
