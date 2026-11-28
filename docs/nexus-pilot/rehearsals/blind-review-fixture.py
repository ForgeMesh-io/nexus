"""Exercise the review handoff with invented reports and durations only."""

from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
from secrets import token_hex, SystemRandom
import subprocess
import sys
from tempfile import TemporaryDirectory


REVIEWER = r'''
import json
from pathlib import Path
import re
import sys

assert not Path("/tmp").exists() and not Path("/home").exists()
packet = json.load(sys.stdin)
assert set(packet) == {"reports", "evidence"}, "unexpected packet fields"
assert set(packet["evidence"]) == {"revision", "path", "lines"}
revision, path, lines = (packet["evidence"][k] for k in ("revision", "path", "lines"))
assert revision == "f" * 40
assert all(re.fullmatch(r"[0-9a-f]{16}", row["report_id"]) for row in packet["reports"])
assert all(set(row) == {"report_id", "task_id", "report"} for row in packet["reports"])
assert all(row["task_id"] == "showcase-hours" for row in packet["reports"])

decisions, effort = [], []
for row in packet["reports"]:
    report_id = row["report_id"]
    # Simulate reaching the review cap on the last item without deciding it.
    if len(decisions) == len(packet["reports"]) - 1:
        decisions.append(dict(report_id=report_id, outcome="unreviewed", checks={},
                              reason="Synthetic review cap reached", label=None))
        effort.append(dict(report_id=report_id, active_seconds=180))
        break
    claim, citation, action = row["report"].splitlines()
    cited = citation == f"{path}:1–2"
    correct = claim == f"{lines[0]} conflicts with {lines[1]}"
    actionable = action == "Ask the organizer to confirm the opening time before editing."
    checks = dict(scope_safe=True, correct=correct, traceable=cited and correct, actionable=actionable)
    outcome = "pass" if all(checks.values()) else "reject"
    decisions.append(dict(report_id=report_id, outcome=outcome, checks=checks,
                          reason="Source mismatch" if not correct else "Supported by both lines",
                          label="confirm-opening-time" if outcome == "pass" else None))
    effort.append(dict(report_id=report_id, active_seconds=45))
print(json.dumps(dict(decisions=decisions, review_effort=effort, attribution_notes=[])))
'''


def encode(data):
    return json.dumps(data, sort_keys=True).encode()


def rehearse(operator):
    path = "notes/showcase.txt"
    lines = ["Invitation: doors open at 14:00.", "Checklist: doors open at 15:00."]
    correct = f"{lines[0]} conflicts with {lines[1]}"
    reports, key = [], {}
    incorrect = "Both sources say 16:00."
    for arm, claim in (("solo", correct), ("independent", incorrect), ("independent", correct), ("nexus", incorrect)):
        report_id = token_hex(8)
        report = f"{claim}\n{path}:1–2\nAsk the organizer to confirm the opening time before editing."
        reports.append(dict(report_id=report_id, task_id="showcase-hours", report=report))
        key[report_id] = dict(run=arm, report_sha256=sha256(report.encode()).hexdigest())
    SystemRandom().shuffle(reports)
    packet = dict(reports=reports, evidence=dict(revision="f" * 40, path=path, lines=lines))
    (operator / "key.json").write_bytes(encode(key))
    (operator / "operator-effort.json").write_bytes(encode({
        "run_specific": {"solo": {"setup": 30}, "independent": {"setup": 0}, "nexus": {"setup": None}},
        "shared": {"study_setup": 120},
    }))

    python = str(Path(sys.executable).resolve())
    assert Path(python).is_relative_to("/usr"), "Run with the system Python under /usr"
    reviewer = ["bwrap", "--unshare-net", "--clearenv", "--ro-bind", "/usr", "/usr",
                "--symlink", "usr/lib", "/lib64", "--chdir", "/", "--", python, "-I", "-c", REVIEWER]
    result = subprocess.run(reviewer, input=encode(packet), capture_output=True, check=True, timeout=10)
    leaked = subprocess.run(reviewer, input=encode(packet | {"arm_map": key}), capture_output=True, timeout=10)
    assert leaked.returncode != 0 and b"unexpected packet fields" in leaked.stderr and not leaked.stdout

    returned = json.loads(result.stdout)
    decisions, effort, notes = (returned[k] for k in ("decisions", "review_effort", "attribution_notes"))
    ids = [row["report_id"] for row in reports]
    assert [row["report_id"] for row in decisions] == [row["report_id"] for row in effort] == ids
    assert len(set(ids)) == 4 and not notes
    outcomes = {row["outcome"] for row in decisions}
    assert outcomes == {"pass", "reject", "unreviewed"}
    assert all(set(row) == {"report_id", "active_seconds"} for row in effort)
    for report, row in zip(reports, decisions, strict=True):
        assert set(row) == {"report_id", "outcome", "checks", "reason", "label"}
        if row["outcome"] != "unreviewed":
            assert row["outcome"] == ("pass" if report["report"].startswith(correct) else "reject")
    assert effort[-1]["active_seconds"] == 180 and decisions[-1]["outcome"] == "unreviewed"

    sheet = operator / "closed-sheet.json"
    sheet.write_bytes(encode(dict(decisions=decisions, attribution_notes=notes)))
    digest = sha256(sheet.read_bytes()).hexdigest()
    (operator / "review-effort.json").write_bytes(encode(effort))

    # The operator joins only after the blind sheet has been captured.
    stored_key = json.loads((operator / "key.json").read_bytes())
    stored_effort = json.loads((operator / "operator-effort.json").read_bytes())
    seconds_by_run = Counter()
    for row in effort:
        seconds_by_run[stored_key[row["report_id"]]["run"]] += row["active_seconds"]
    assert all(stored_key[row["report_id"]]["report_sha256"] == sha256(row["report"].encode()).hexdigest()
               for row in reports)
    assert set(seconds_by_run) == set(stored_effort["run_specific"])
    assert sum(seconds_by_run.values()) == 315 and stored_effort["shared"]["study_setup"] == 120
    assert [item["setup"] for item in stored_effort["run_specific"].values()].count(None) == 1
    assert [item["setup"] for item in stored_effort["run_specific"].values()].count(0) == 1
    assert sha256(sheet.read_bytes()).hexdigest() == digest
    print("PASS: 4 opaque rows; pass, reject and unreviewed exercised; injected arm map refused")
    print("PASS: review and operator effort separate; shared setup, explicit zero, and missing time preserved")
    print(f"Closed synthetic sheet SHA-256: {digest}")
    print("No human timed; no official scores, real reports, or ledger writes.")


if __name__ == "__main__":
    assert not Path(sys.argv[1]).resolve().is_relative_to("/usr"), "Keep operator artifacts outside /usr"
    with TemporaryDirectory(prefix="blind-review-fixture-", dir=sys.argv[1]) as directory:
        operator = Path(directory) / "operator"
        operator.mkdir(mode=0o700)
        rehearse(operator)
