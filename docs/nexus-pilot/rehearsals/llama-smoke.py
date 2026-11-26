"""Synthetic engine qualification only; run against a disposable isolated server."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from http.client import HTTPConnection
import json
from pathlib import Path
from runpy import run_path
from threading import Barrier
from time import monotonic, sleep

module = run_path(str(Path(__file__).with_name("trial-budget.py")))
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("port", type=int)
parser.add_argument("mode", choices=("complete", "cancel", "late"))
args = parser.parse_args()
budget = module["Budget"](2)


def slots():
    connection = HTTPConnection("127.0.0.1", args.port, timeout=0.6)
    try:
        connection.request("GET", "/slots")
        with connection.getresponse() as response:
            assert response.status == 200
            return json.load(response)
    finally:
        connection.close()


def wait_for(processing, seconds):
    end = monotonic() + seconds
    while monotonic() < end:
        try:
            if any(slot["is_processing"] for slot in slots()) is processing:
                return True
        except TimeoutError:
            pass
        sleep(0.05)
    return False


assert [slot["n_ctx"] for slot in slots()] == [4096, 4096]
assert wait_for(False, 2), "start with a fresh, idle server"
if args.mode in ("complete", "late"):
    bound, send = module["prepare_llama"](
        args.port, 'There are no tasks. Return exactly this JSON object and nothing else: {"op":"stop"}\nOutput:\n',
    )
if args.mode == "complete":
    simultaneous = Barrier(2, timeout=5)

    def both(deadline, stop):
        simultaneous.wait()
        return send(deadline, stop)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda worker: budget.model(worker, bound, both), range(2)))
    print("Synthetic actions:", results)
    assert results == [{"op": "stop"}] * 2
    assert all(row["requests"] == 1 and 0 < row["tokens"] <= 4096 and row["unknown"] == 0 for row in budget.snapshot())
elif args.mode == "cancel":
    bound, send = module["prepare_llama"](args.port, "Continue listing the numbers in English for as long as possible.\n1 one\n2 two\n3 three\n")
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(budget.model, 0, bound, send)
        assert wait_for(True, 5), "backend did not begin the fixture"
        start = monotonic()
        budget.cancel()
        try:
            pending.result(timeout=2)
        except OSError:
            print("Client released after cancel (s):", round(monotonic() - start, 3))
        else:
            raise AssertionError("cancelled response unexpectedly returned")
        print("Backend idle within 8 s:", wait_for(False, 8))
    assert budget.snapshot()[0]["unknown"] == 1
else:
    def deliver_after_stop(deadline, stop):
        action, usage = send(deadline, stop)
        assert action == {"op": "stop"} and usage.total() > 0
        print("Real completion held at the dispatcher boundary:", action, usage)
        budget.cancel()
        return action, usage

    try:
        budget.model(0, bound, deliver_after_stop)
    except module["Refused"] as exc:
        assert str(exc) == "cancelled"
        print("Late action discarded:", exc)
    else:
        raise AssertionError("late action unexpectedly returned")
    assert budget.snapshot()[0]["unknown"] == 0
    assert budget.snapshot()[0]["tokens"] == budget.usage()[0].total() > 0
if args.mode != "complete":
    try:
        budget.tool(0, lambda *_: None)
    except module["Refused"] as exc:
        assert str(exc) == "cancelled"
    else:
        raise AssertionError("dispatcher admitted a tool call after cancellation")
    assert budget.snapshot()[0]["tools"] == 0
print("Accounting:", budget.snapshot())
print("Known usage:", budget.usage())
