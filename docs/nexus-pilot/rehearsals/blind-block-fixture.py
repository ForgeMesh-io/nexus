"""Check local delivery and retention for an invented three-arm block."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory


def write_json(path, record):
    path.write_text(json.dumps(record, sort_keys=True), encoding="utf-8")


def handoff(packet, deviation, operator, inbox):
    if deviation is not None:
        write_json(operator / "deviation.json", deviation)
        return
    write_json(inbox / "evaluator.json", packet)


def rehearse(root, blocked):
    operator = root / "operator"
    inbox = root / "inbox"
    operator.mkdir(parents=True, mode=0o700)
    inbox.mkdir(mode=0o700)

    source = "receipts/nexus/desk.txt" if blocked else "notes/desk.txt"
    reports = [
        {"report_id": "7b20", "task_id": "desk-hours", "text": "The notice says 09:00 (`notes/doors.txt:1`)."},
        {"report_id": "c931", "task_id": "desk-hours", "text": "The notice lists the east entrance (`notes/doors.txt:2`)."},
        {"report_id": "25ea", "task_id": "desk-hours", "text": f"The desk opens at 10:00 (`{source}:1`)."},
    ]
    evidence = {"notes/doors.txt": ["Doors open at 09:00.", "Use the east entrance."],
                source: ["The desk opens at 10:00."]}
    resources = {
        "solo": {"model_attempts": 2, "tool_attempts": 3, "tokens": 120, "elapsed_seconds": 22},
        "independent": {"model_attempts": 2, "tool_attempts": 1, "tokens": 100, "elapsed_seconds": 19},
        "nexus": {"model_attempts": 3, "tool_attempts": 4, "tokens": 130, "elapsed_seconds": 31},
    }
    packet = {"reports": reports, "evidence": evidence, "revision": "e" * 40}
    write_json(operator / "originals.json", packet)
    write_json(operator / "resources.json", resources)
    write_json(operator / "arm-map.json", {"7b20": "solo", "c931": "independent", "25ea": "nexus"})
    archives = {path: path.read_bytes() for path in operator.iterdir()}

    deviation = None
    if blocked:
        # The operator has checked the source path and cannot remove it without changing the citation.
        deviation = {"status": "unscored", "reason": "attribution_in_citation", "report_id": "25ea",
                     "source_path": source}
    handoff(packet, deviation, operator, inbox)

    if blocked:
        assert not list(inbox.iterdir()), "An irreducible cue must prevent every reviewer artifact"
        assert json.loads((operator / "deviation.json").read_bytes()) == deviation
    else:
        assert sorted(path.name for path in inbox.iterdir()) == ["evaluator.json"]
        assert json.loads((inbox / "evaluator.json").read_bytes()) == packet
        assert not (operator / "deviation.json").exists()
    for path, original in archives.items():
        assert path.read_bytes() == original, f"Handoff changed {path.name}"


if __name__ == "__main__":
    with TemporaryDirectory() as directory:
        scratch = Path(directory)
        rehearse(scratch / "control", blocked=False)
        print("CONTROL: 3 of 3 reports delivered in one local packet; no verdicts")
        rehearse(scratch / "blocked", blocked=True)
        print("BLOCKED: 0 of 3 reports delivered; private deviation attribution_in_citation; block unscored")
        print("PASS: original reports, pinned evidence, arm map and all 3 resource records byte-identical")
