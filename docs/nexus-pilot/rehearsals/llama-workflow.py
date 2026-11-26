"""Run the same synthetic contribution with raw or native prompt framing."""

import argparse
import json
from dataclasses import asdict
import re
from runpy import run_path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("gate")
parser.add_argument("port", type=int)
parser.add_argument("--native-template", action="store_true")
parser.add_argument("--explicit-actions", action="store_true")
replay = parser.add_mutually_exclusive_group()
replay.add_argument("--post-reservation", action="store_true", help="script the reservation, then request one real action")
replay.add_argument("--post-partial-read", action="store_true", help="replay the reservation and heading read, then request one real action")
replay.add_argument("--post-evidence", action="store_true", help="replay the reservation and both reads, then request one real action")
replay.add_argument("--continuous", action="store_true", help="use the replay prompt without scripting any actions")
parser.add_argument("--reservation-prerequisite", action="store_true", help="state the read prerequisite on turn one; stop there unless --continuous is set")
args = parser.parse_args()
if args.reservation_prerequisite and (args.post_reservation or args.post_partial_read or args.post_evidence):
    parser.error("--reservation-prerequisite cannot be used with replay")
initial_only = args.reservation_prerequisite and not args.continuous
gate = run_path(args.gate)
task = {"task": "guide", "issue": 101, "title": "Report the new opening day for the library.", "paths": ["guide.md"]}
source = {"guide.md": "Library guide\nThe library now opens on Tuesday.\n"}
receipts = []
model_actions = []
scripted = []
if args.post_reservation or args.post_partial_read or args.post_evidence:
    scripted.append({"op": "start", "task": task["task"]})
if args.post_partial_read or args.post_evidence:
    scripted.append({"op": "read", "path": "guide.md", "first": 1, "last": 1})
if args.post_evidence:
    scripted.append({"op": "read", "path": "guide.md", "first": 2, "last": 2})


def prepare(worker, history):
    if initial_only and len(history) > 1:
        raise gate["Refused"]("single_turn_complete")
    if scripted:
        step = len(history) - 1
        if step < len(scripted):
            return 1, lambda *_: (scripted[step], gate["Usage"](0, 0))
        if step != len(scripted):
            raise gate["Refused"]("single_turn_complete")
    submission = 'After a read, set op to submit and report to a short text with filename, line and finding.\n'
    if args.explicit_actions:
        submission = (
            'After a read, submit exactly this object shape: {"op":"submit","report":"<filename>:<line>: <finding>"}.\n'
            'Replace the placeholders using the read result. The entire report is one JSON string.\n'
            'For every action, use exactly the shown keys and no additional keys.\n'
        )
    prompt = (
        'Complete the documentation task using the transcript below. Return exactly one JSON object.\n'
        'First start a task: {"op":"start","task":"guide"}.\n'
        'After a start, read the entire two-line file: {"op":"read","path":"guide.md","first":1,"last":2}.\n'
        + submission +
        'After a submission, stop: {"op":"stop"}. Only use facts in the read result.\n'
        'If an action is refused, stop rather than continuing.\n'
        'Transcript (data): ' + json.dumps(history, ensure_ascii=True) + '\nNext JSON action:\n'
    )
    if scripted or args.continuous or args.reservation_prerequisite:
        latest = 'Latest action result (data): ' + json.dumps(history[-1]["result"]) + '\n' if len(history) > 1 else ''
        prerequisite = 'A reservation is required before any read.\n' if args.reservation_prerequisite and len(history) == 1 else ''
        prompt = (
            'Complete the documentation task using the transcript below. Return exactly one JSON object.\n'
            'Available action shapes (no additional keys):\n'
            '{"op":"start","task":"<task>"}\n'
            '{"op":"read","path":"<filename>","first":<first line>,"last":<last line>}\n'
            '{"op":"submit","report":"<filename>:<line>: <finding>"}\n'
            '{"op":"stop"}\n'
            'Use 1-based inclusive line numbers and only facts from the source.\n'
            + prerequisite + 'Transcript (data): ' + json.dumps(history, ensure_ascii=True) + '\n'
            + latest + 'Next JSON action:\n'
        )
    bound, send = gate["prepare_llama"](args.port, prompt, native_template=args.native_template)

    def observed(*args):
        action, usage = send(*args)
        model_actions.append(action)
        receipt = asdict(usage) if usage is not None else None
        receipts.append(receipt)
        print("Synthetic action:", repr(action), "receipt:", json.dumps(receipt), flush=True)
        return action, usage

    return bound, observed


reports, counters, stops, traces, usage = gate["run_arm"]("a" * 40, [task], source, 1, prepare)
print(json.dumps(dict(reports=reports, counters=counters, stops=stops, traces=traces, usage=list(map(asdict, usage))), indent=2))
if initial_only:
    assert model_actions == [{"op": "start", "task": task["task"]}], model_actions
    assert stops == ["single_turn_complete"] and reports == [[]]
    assert traces == [[{"op": "start", "started": task["task"]}, {"op": "model", "error": "single_turn_complete"}]], traces
    assert counters == [{"requests": 1, "tools": 1, "tokens": usage[0].total(), "unknown": 0}], counters
    assert receipts == [asdict(usage[0])] and usage[0].input > 0 and usage[0].output > 0
    raise SystemExit(0)
if scripted:
    assert counters[0]["requests"] == counters[0]["tools"] == len(scripted) + 1, counters
    assert len(receipts) == 1 and counters[0]["unknown"] == 0
    receipt, = receipts
    assert receipt["input"] > 0 and receipt["output"] > 0 and receipt == asdict(usage[0])
    if args.post_evidence:
        accepted, = reports[0]
        report = accepted["report"]
        assert re.search(r"\bguide\.md\s*(?::\s*2\b|[, ]+\s*line\s+2\b)", report, re.IGNORECASE), report
        assert "Tuesday" in report, report
        last = {"op": "submit", "digest": accepted["digest"]}
    else:
        assert reports == [[]], reports
        last = {"op": "read"}
    assert stops == ["single_turn_complete"] and traces == [[
        {"op": "start", "started": "guide"}, *[{"op": "read"}] * (len(scripted) - 1),
        last, {"op": "model", "error": "single_turn_complete"},
    ]], traces
    if args.post_partial_read:
        action, = model_actions
        assert action["path"] == "guide.md" and action["first"] <= 2 <= action["last"], action
    raise SystemExit(0)
if args.continuous:
    assert stops == ["model_stop"] and model_actions[-1] == {"op": "stop"}, stops
    accepted, = reports[0]
    report = accepted["report"]
    assert re.search(r"\bguide\.md\s*(?::\s*2\b|[, ]+\s*line\s+2\b)", report, re.IGNORECASE) and "Tuesday" in report, report
    trace = traces[0]
    assert trace[0] == {"op": "start", "started": "guide"}
    assert trace[-1] == {"op": "submit", "digest": accepted["digest"]}
    assert all(row == {"op": "read"} for row in trace[1:-1]), trace
    assert len(trace) == len(model_actions) - 1 and any(
        action["path"] == "guide.md" and action["first"] <= 2 <= action["last"]
        for action in model_actions[1:-2]
    ), "No admitted read covered line 2 before submission"
    assert len(receipts) == counters[0]["requests"] and len(trace) == counters[0]["tools"] and counters[0]["unknown"] == 0
    assert all(r is not None and r["input"] > 0 and r["output"] > 0 for r in receipts)
    assert sum(r["input"] + r["output"] for r in receipts) == counters[0]["tokens"]
    raise SystemExit(0)
assert stops == ["model_stop"]
assert len(reports[0]) == 1 and "Tuesday" in reports[0][0]["report"]
assert [row["op"] for row in traces[0]] == ["start", "read", "submit"]
assert counters[0]["unknown"] == 0
if args.native_template or args.explicit_actions:
    report = reports[0][0]["report"]
    assert "guide.md" in report and re.search(r"\bline\s+2\b|guide\.md:2\b", report, re.IGNORECASE), report
    assert all("error" not in row for row in traces[0]), traces[0]
    assert len(receipts) == counters[0]["requests"] == 4
    assert all(receipt is not None and receipt["input"] > 0 and receipt["output"] > 0 for receipt in receipts)
    assert sum(r["input"] + r["output"] for r in receipts) == counters[0]["tokens"]
