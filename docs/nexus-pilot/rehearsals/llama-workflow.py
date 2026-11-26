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
args = parser.parse_args()
gate = run_path(args.gate)
task = {"task": "guide", "issue": 101, "title": "Report the new opening day for the library.", "paths": ["guide.md"]}
source = {"guide.md": "Library guide\nThe library now opens on Tuesday.\n"}
receipts = []


def prepare(worker, history):
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
    bound, send = gate["prepare_llama"](args.port, prompt, native_template=args.native_template)

    def observed(*args):
        action, usage = send(*args)
        receipt = asdict(usage) if usage is not None else None
        receipts.append(receipt)
        print("Synthetic action:", repr(action), "receipt:", json.dumps(receipt), flush=True)
        return action, usage

    return bound, observed


reports, counters, stops, traces, usage = gate["run_arm"]("a" * 40, [task], source, 1, prepare)
print(json.dumps(dict(reports=reports, counters=counters, stops=stops, traces=traces, usage=list(map(asdict, usage))), indent=2))
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
