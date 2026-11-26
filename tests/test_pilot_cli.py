import json
import shutil
import subprocess
import sys

import pytest


BASE = "b" * 40


def run(path, action, **payload):
    result = subprocess.run([sys.executable, "-m", "forgemesh.pilot_cli", str(path), action],
                            input=json.dumps(payload), text=True, capture_output=True, timeout=10)
    assert result.stderr == ""
    return result.returncode, json.loads(result.stdout)


def call(path, action, **payload):
    code, result = run(path, action, **payload)
    assert code == 0, result
    return result


def test_local_cycle_discovers_validates_and_exports_one_authorized_report(tmp_path):
    state = tmp_path / "nexus.db"
    destination = tmp_path / "receipts"
    destination.mkdir()
    call(state, "initialize", repository="example/project")
    for actor, role in [("alice", "contributor"), ("bob", "reviewer"),
                        ("carol", "maintainer"), ("worker", "publisher")]:
        token = call(state, "enroll", actor=actor, owner=actor, role=role)
        assert isinstance(token, str) and len(token) == 43
        if actor == "alice":
            contributor = token
        elif actor == "bob":
            reviewer = token
        elif actor == "carol":
            maintainer = token
        else:
            publisher = token
    call(state, "add-task", task="recipe", issue=7, base=BASE, title="Check the recipe")
    task, = call(state, "discover", token=contributor)["tasks"]
    assert task["base"] == BASE
    lease = call(state, "claim", token=contributor, task=task["id"])
    report = "The recipe omits the final step."
    digest = call(state, "submit", token=contributor, task="recipe", lease=lease, report=report)
    item, = call(state, "discover", token=reviewer)["tasks"]
    assert (item["digest"], item["report"]) == (digest, report)
    assert call(state, "review", token=reviewer, task="recipe", digest=digest,
                verdict="pass", evidence="Checked recipe at pinned revision") == "validated"
    preview = call(state, "inspect-report", token=maintainer, task="recipe")
    assert (preview["issue"], preview["base"], preview["report"], preview["digest"], preview["evidence"]) == (
        7, BASE, report, digest, "Checked recipe at pinned revision")
    assert run(state, "inspect-report", token=contributor, task="recipe") == (1, {"error": "unauthorized"})
    assert run(state, "authorize", token=contributor, task="recipe", digest=digest) == (
        1, {"error": "unauthorized"})
    marker = call(state, "authorize", token=maintainer, task="recipe", digest=digest)
    request = {"token": publisher, "task": "recipe", "current_base": BASE,
               "destination": str(destination)}
    assert call(state, "publish-local", **request) == 7
    assert call(state, "publish-local", **request) == 7
    receipt, = destination.iterdir()
    assert receipt.name == f"{marker}.json"
    assert json.loads(receipt.read_text()) == {
        "repository": "example/project", "issue": 7, "base": BASE, "marker": marker,
        "digest": digest, "report": report,
    }
    audit = call(state, "audit")
    assert [event["event"] for event in audit][-3:] == ["authorized", "dispatch_started", "published"]
    assert all(token not in json.dumps(audit) for token in (contributor, reviewer, maintainer, publisher))
    assert call(state, "stop", token=maintainer) is None
    assert run(state, "discover", token=contributor) == (1, {"error": "stopped"})


def test_cli_rejects_extra_fields_and_unknown_operations(tmp_path):
    state = tmp_path / "nexus.db"
    assert run(state, "initialize", repository="example/project", token="unexpected") == (
        1, {"error": "invalid_input"})
    assert run(state, "_db") == (1, {"error": "unknown_action"})
    assert not state.exists()


def test_zero_agent_and_publication_budgets_are_valid(tmp_path):
    state = tmp_path / "nexus.db"
    call(state, "initialize", repository="example/project", active_limit=0, publication_limit=0)
    writer = call(state, "enroll", actor="writer", owner="alice", role="contributor")
    call(state, "add-task", task="recipe", issue=7, base=BASE, title="Check the recipe")
    assert call(state, "discover", token=writer)["tasks"] == []
    assert run(state, "claim", token=writer, task="recipe") == (1, {"error": "capacity"})


def test_cli_rejects_oversize_and_duplicate_json_fields(tmp_path):
    state = tmp_path / "nexus.db"
    for payload in ['{"repository":"example/project","repository":"example/other"}', ' ' * 65_537]:
        result = subprocess.run([sys.executable, "-m", "forgemesh.pilot_cli", str(state), "initialize"],
                                input=payload, text=True, capture_output=True, timeout=10)
        assert result.returncode == 1
        assert json.loads(result.stdout) == {"error": "invalid_input"}
    assert not state.exists()


@pytest.mark.skipif(not shutil.which("sqlite3"), reason="sqlite3 CLI is unavailable")
def test_operator_snapshot_restores_stop_and_revocation_without_replacing_source(tmp_path):
    state = tmp_path / "nexus.db"
    backup = tmp_path / "backup"
    backup.mkdir(mode=0o700)
    snapshot = backup / "pilot.db"
    call(state, "initialize", repository="example/project")
    writer = call(state, "enroll", actor="writer", owner="alice", role="contributor")
    reviewer = call(state, "enroll", actor="reviewer", owner="bob", role="reviewer")
    maintainer = call(state, "enroll", actor="maintainer", owner="carol", role="maintainer")
    call(state, "revoke", token=maintainer, actor="writer")
    call(state, "stop", token=maintainer)
    subprocess.run(["sqlite3", "-readonly", str(state), f'.backup "{snapshot}"'], check=True, timeout=5)
    assert subprocess.check_output(["sqlite3", "-readonly", str(snapshot), "PRAGMA integrity_check;"],
                                   timeout=5, text=True).strip() == "ok"
    restored = tmp_path / "restored.db"
    shutil.copyfile(snapshot, restored)
    assert call(restored, "audit") == call(state, "audit")
    assert run(restored, "discover", token=writer) == (1, {"error": "unauthorized"})
    assert run(restored, "discover", token=reviewer) == (1, {"error": "stopped"})
