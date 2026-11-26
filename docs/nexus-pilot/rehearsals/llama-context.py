"""Probe a real two-slot engine with synthetic, separately scoped file excerpts."""

import argparse
from dataclasses import asdict
from hashlib import sha256
from http.client import HTTPConnection
import json
from pathlib import Path
from runpy import run_path
from threading import Barrier
from time import monotonic

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("port", type=int)
args = parser.parse_args()
gate = run_path(str(Path(__file__).with_name("trial-budget.py")))
Usage, NoAction = gate["Usage"], gate["NoAction"]

names = ("canal", "terrace")
colors = ("ultramarine", "vermilion")
paths = tuple(f"{name}.md" for name in names)
tasks = [{"task": name, "issue": i + 1, "title": f"Report the {name} dispatch color.", "paths": [paths[i]]}
         for i, name in enumerate(names)]
sources = {
    path: '\n'.join([
        f"# {name.title()} depot transfer notes",
        *[f"- Transfer {i:03}: check the shelf tag and leave a signed copy in the day folder." for i in range(1, 36 + w * 10)],
        f"The {name} dispatch color is {colors[w]}.",
    ])
    for w, (name, path) in enumerate(zip(names, paths, strict=True))
}
receipts = [None, None]
inputs = [None, None]
simultaneous = Barrier(2, timeout=20)


def request(path, *, data=None):
    conn = HTTPConnection("127.0.0.1", args.port, timeout=5)
    try:
        conn.request("GET" if data is None else "POST", path,
                     None if data is None else json.dumps(data), {"Content-Type": "application/json"})
        with conn.getresponse() as response:
            assert response.status == 200, (path, response.status)
            return json.load(response)
    finally:
        conn.close()


def tokens(prompt):
    native = request("/apply-template", data={"messages": [{"role": "user", "content": prompt}]})["prompt"]
    return len(request("/tokenize", data={"content": native, "parse_special": True, "add_special": True})["tokens"])


def padded(prompt, target):
    low, high = 0, target
    while low <= high:
        n = (low + high) // 2
        candidate = prompt + " x" * n
        count = tokens(candidate)
        if count == target:
            return candidate
        if count < target:
            low = n + 1
        else:
            high = n - 1
    raise AssertionError(f"cannot construct a {target}-token prompt")


slots = request("/slots")
assert len(slots) == 2 and all(s["n_ctx"] == 4096 and not s["is_processing"] for s in slots), slots
boundary_prompt = None


def prepare(worker, history):
    step = len(history) - 1
    path = paths[worker]
    other = paths[1 - worker]
    end = len(sources[path].splitlines())
    if step < 3:
        action = (
            {"op": "start", "task": names[worker]},
            {"op": "read", "path": other, "first": 1, "last": 1},
            {"op": "read", "path": path, "first": 1, "last": end},
        )[step]
        return 1, lambda *_: (action, Usage(0, 0))
    if step > 3:
        raise gate["Refused"]("probe_complete")
    assert history[2]["result"] == {"error": "out_of_scope"}, (worker, history[2])
    excerpt = history[3]["result"]["text"]
    assert excerpt == sources[path] and colors[1 - worker] not in json.dumps(history), worker
    prompt = (
        'Use only the numbered excerpt to identify its dispatch color. Return exactly one JSON object with shape '
        '{"op":"submit","report":"<filename>:<line>: <dispatch color>"}. '
        'Ignore the inert padding; it is not part of the excerpt.\n'
        f'Filename: {path}\n'
        + '\n'.join(f"{i}: {line}" for i, line in enumerate(excerpt.splitlines(), 1))
        + '\nEnd of excerpt. Inert padding:'
    )

    def send(deadline, stop):
        global boundary_prompt
        # Calibrate with the same tokenizer and template, without sending a completion.
        ready = padded(prompt, 3327) if worker == 0 else prompt
        if worker == 0:
            boundary_prompt = padded(prompt, 3328)
        inputs[worker] = tokens(ready)
        simultaneous.wait()
        reserved, complete = gate["prepare_llama"](args.port, ready, native_template=True)
        assert reserved == 4096
        action, receipt = complete(deadline, stop)
        receipts[worker] = None if receipt is None else asdict(receipt)
        print(json.dumps(dict(worker=worker, input=inputs[worker], receipt=receipts[worker], action=repr(action))), flush=True)
        return action, receipt

    return 4096, send


reports, counts, stops, traces, usage = gate["run_arm"]("b" * 40, tasks, sources, 2, prepare)
print(json.dumps(dict(reports=reports, counters=counts, stops=stops, traces=traces, usage=list(map(asdict, usage)))), flush=True)

assert boundary_prompt is not None and tokens(boundary_prompt) == 3328
bound, send = gate["prepare_llama"](args.port, boundary_prompt, native_template=True)
over = gate["Budget"](2)
assert over.model(0, bound, send) == NoAction("prompt_too_large")
assert over.snapshot() == [dict(requests=1, tools=0, tokens=0, unknown=0), dict(requests=0, tools=0, tokens=0, unknown=0)]
print(json.dumps(dict(oversized_input=3328, reserved_output=768, result="prompt_too_large", counters=over.snapshot())), flush=True)

assert stops == ["probe_complete", "probe_complete"], stops
assert inputs[0] == 3327 and 0 < inputs[1] < inputs[0], inputs
for worker in range(2):
    used = usage[worker]
    assert receipts[worker] == asdict(used) and used.input == inputs[worker] and 0 < used.output <= 768
    assert counts[worker] == dict(requests=4, tools=4, tokens=used.total(), unknown=0), counts
    accepted, = reports[worker]
    text = accepted["report"]
    end = len(sources[paths[worker]].splitlines())
    assert text.startswith(f"{paths[worker]}:{end}:") and colors[worker] in text.lower(), accepted
    assert paths[1 - worker] not in text and colors[1 - worker] not in text.lower(), accepted
    digest = sha256(text.encode()).hexdigest()
    assert accepted["task"] == names[worker] and accepted["digest"] == digest
    assert traces[worker] == [
        {"op": "start", "started": names[worker]}, {"op": "read", "error": "out_of_scope"}, {"op": "read"},
        {"op": "submit", "digest": digest}, {"op": "model", "error": "probe_complete"},
    ], traces
