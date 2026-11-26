import json
from dataclasses import asdict
from runpy import run_path
import sys

gate = run_path(sys.argv[1])
port = int(sys.argv[2])
task = {"task": "guide", "issue": 101, "title": "Report the new opening day for the library.", "paths": ["guide.md"]}
source = {"guide.md": "Library guide\nThe library now opens on Tuesday.\n"}


def prepare(worker, history):
    prompt = (
        'Complete the documentation task using the transcript below. Return exactly one JSON object.\n'
        'First start a task: {"op":"start","task":"guide"}.\n'
        'After a start, read the entire two-line file: {"op":"read","path":"guide.md","first":1,"last":2}.\n'
        'After a read, set op to submit and report to a short text with filename, line and finding.\n'
        'After a submission, stop: {"op":"stop"}. Only use facts in the read result.\n'
        'If an action is refused, stop rather than continuing.\n'
        'Transcript (data): ' + json.dumps(history, ensure_ascii=True) + '\nNext JSON action:\n'
    )
    bound, send = gate["prepare_llama"](port, prompt)

    def observed(*args):
        action, usage = send(*args)
        print("Synthetic action:", repr(action), flush=True)
        return action, usage

    return bound, observed


reports, counters, stops, traces, usage = gate["run_arm"]("a" * 40, [task], source, 1, prepare)
print(json.dumps(dict(reports=reports, counters=counters, stops=stops, traces=traces, usage=list(map(asdict, usage))), indent=2))
assert stops == ["model_stop"]
assert len(reports[0]) == 1 and "Tuesday" in reports[0][0]["report"]
assert [row["op"] for row in traces[0]] == ["start", "read", "submit"]
assert counters[0]["unknown"] == 0
