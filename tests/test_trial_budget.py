"""Offline checks for the experimental runner's dispatch gate."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from runpy import run_path
from threading import Barrier, Event

import pytest
from forgemesh.pilot import Pilot

gate = run_path(str(Path(__file__).resolve().parents[1] / "docs/nexus-pilot/rehearsals/trial-budget.py"))
Budget, Refused, Usage = (gate[name] for name in ("Budget", "Refused", "Usage"))


def never(*args):
    pytest.fail("a refused call was dispatched")


def reply(*args):
    return "ok", Usage(100, 20, cached=80, reasoning=10)


@pytest.mark.parametrize("arm, workers", [("solo", 1), ("independent", 2), ("nexus", 2)])
def test_frozen_attempt_partitions_under_contention(arm, workers):
    budget = Budget(workers)
    entered = Barrier(workers + 1, timeout=5)
    finish = Event()

    def send(deadline, stop):
        entered.wait()
        assert finish.wait(5)
        return reply()

    with ThreadPoolExecutor(max_workers=workers) as pool:
        first = [pool.submit(budget.model, worker, 1000, send) for worker in range(workers)]
        try:
            entered.wait()
            for worker in range(workers):
                with pytest.raises(Refused, match="in_flight"):
                    budget.model(worker, 1000, never)
        finally:
            finish.set()
        assert [task.result() for task in first] == ["ok"] * workers

    for worker in range(workers):
        # One conclusively zero-charge failed response; the retry is a separate attempt.
        assert budget.model(worker, 200, lambda *_: ("429", Usage(0, 0))) == "429"
        for _ in range(12 // workers - 2):
            assert budget.model(worker, 200, reply) == "ok"
        with pytest.raises(Refused, match="request_limit"):
            budget.model(worker, 200, never)

        def failed_tool(*args):
            raise ValueError("denied by tool")

        with pytest.raises(ValueError, match="denied by tool"):
            budget.tool(worker, failed_tool)
        for _ in range(24 // workers - 1):
            assert budget.tool(worker, lambda *_: "fixture") == "fixture"
        with pytest.raises(Refused, match="tool_limit"):
            budget.tool(worker, never)
    assert sum(w["requests"] for w in budget.snapshot()) == 12
    assert sum(w["tools"] for w in budget.snapshot()) == 24
    assert sum(w["tokens"] for w in budget.snapshot()) == (12 - workers) * 120


@pytest.mark.parametrize("workers", [1, 2])
def test_reservation_uses_input_plus_output_without_borrowing_or_double_counting(workers):
    budget = Budget(workers)
    cap = 64000 // workers
    with pytest.raises(Refused, match="token_limit"):
        budget.model(0, cap + 1, never)
    assert budget.model(0, cap, lambda *_: ("first", Usage(cap - 120, 1, cached=200))) == "first"
    with pytest.raises(Refused, match="token_limit"):
        budget.model(0, 120, never)
    assert budget.model(0, 119, lambda *_: ("last", Usage(100, 19, cached=80, reasoning=10))) == "last"
    with pytest.raises(Refused, match="token_limit"):
        budget.model(0, 1, never)
    assert budget.snapshot()[0] == {"requests": 2, "tools": 0, "tokens": cap, "unknown": 0}


@pytest.mark.parametrize("usage, reason, tokens, unknown", [
    (None, "unknown_usage", 0, 1),
    (Usage(10, 3, cached=11), "unknown_usage", 0, 1),
    (Usage(10, 3, reasoning=4), "unknown_usage", 0, 1),
    (Usage(10, -1), "unknown_usage", 0, 1),
    (Usage(199, 2), "usage_over_bound", 201, 0),
])
def test_unverifiable_or_excess_usage_stops_the_whole_arm(usage, reason, tokens, unknown):
    budget = Budget(2)
    with pytest.raises(Refused, match=reason):
        budget.model(0, 200, lambda *_: ("not accepted", usage))
    with pytest.raises(Refused, match=reason):
        budget.model(1, 200, never)
    with pytest.raises(Refused, match=reason):
        budget.tool(1, never)
    assert budget.snapshot()[0] == {"requests": 1, "tools": 0, "tokens": tokens, "unknown": unknown}


def test_transport_failure_charges_an_attempt_and_prevents_retry():
    budget = Budget(1)

    def lost(*args):
        raise TimeoutError("response lost")

    with pytest.raises(TimeoutError, match="response lost"):
        budget.model(0, 200, lost)
    with pytest.raises(Refused, match="unknown_usage"):
        budget.model(0, 200, never)
    assert budget.snapshot()[0] == {"requests": 1, "tools": 0, "tokens": 0, "unknown": 1}


@pytest.mark.parametrize("cancel", [False, True])
def test_late_or_cancelled_output_is_not_accepted_but_usage_is_kept(cancel):
    now = [10.0]
    budget = Budget(2, clock=lambda: now[0])

    def slow(deadline, stop):
        assert deadline == 910.0 and not stop.is_set()
        if cancel:
            budget.cancel()
            assert stop.is_set()
        else:
            now[0] = deadline
        return reply()

    reason = "cancelled" if cancel else "deadline"
    with pytest.raises(Refused, match=reason):
        budget.model(0, 200, slow)
    with pytest.raises(Refused, match=reason):
        budget.model(1, 200, never)
    with pytest.raises(Refused, match=reason):
        budget.tool(1, never)
    assert budget.snapshot()[0] == {"requests": 1, "tools": 0, "tokens": 120, "unknown": 0}


def test_in_flight_tool_result_after_deadline_is_discarded():
    now = [0.0]
    budget = Budget(1, clock=lambda: now[0])

    def slow(deadline, stop):
        now[0] = deadline
        return "do not use"

    with pytest.raises(Refused, match="deadline"):
        budget.tool(0, slow)
    assert budget.snapshot()[0]["tools"] == 1


def test_concurrent_tools_cannot_both_take_the_same_last_slot():
    budget = Budget(2)
    for _ in range(11):
        budget.tool(0, lambda *_: None)
    ready = Barrier(2, timeout=5)

    def contender():
        ready.wait()
        try:
            return budget.tool(0, lambda *_: "ran")
        except Refused as exc:
            return str(exc)

    with ThreadPoolExecutor(max_workers=2) as pool:
        attempts = [pool.submit(contender) for _ in range(2)]
        assert sorted(task.result() for task in attempts) == ["ran", "tool_limit"]
    assert budget.snapshot()[0]["tools"] == 12


def test_unknown_usage_signals_other_in_flight_worker_and_discards_its_output():
    budget = Budget(2)
    entered = Event()

    def second_worker(deadline, stop):
        entered.set()
        assert stop.wait(5)
        return reply()

    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(budget.model, 1, 200, second_worker)
        assert entered.wait(5)
        with pytest.raises(Refused, match="unknown_usage"):
            budget.model(0, 200, lambda *_: ("unknown", None))
        with pytest.raises(Refused, match="unknown_usage"):
            pending.result(timeout=5)
    assert budget.snapshot()[1] == {"requests": 1, "tools": 0, "tokens": 120, "unknown": 0}


@pytest.mark.parametrize("arm, workers", [("solo", 1), ("independent", 2), ("nexus", 2)])
def test_same_action_loop_scopes_reads_and_keeps_private_outputs(tmp_path, arm, workers):
    run_arm = gate["run_arm"]
    base = "a" * 40
    tasks = [dict(task="guide", issue=101, title="Guide", paths=["guide.md"]),
             dict(task="build", issue=102, title="Build", paths=["build.md"])]
    ledger = None
    credentials = []
    if arm == "nexus":
        ledger = Pilot(tmp_path / "pilot.db")
        ledger.initialize("example/project", publication_limit=0, active_limit=2, lease_seconds=900)
        for task in tasks:
            ledger.add_task(base=base, **task)
        credentials = [ledger.enroll(f"worker-{i}", f"owner-{i}", "contributor") for i in range(workers)]
    sources = {"guide.md": "fixture guide", "build.md": "fixture build", "secret": "not in scope"}
    begun = Barrier(workers, timeout=5)
    picked = Barrier(workers, timeout=5)

    def prepare(worker, history):
        step = len(history) - 1
        row = history[-1]
        if step == 0:
            assert row == {"base": base, "tasks": tasks}

        def send(deadline, stop):
            if step == 0:
                begun.wait()
            if step == 1:
                picked.wait()
            if step == 0:
                action = {"op": "start", "task": "guide"}
            elif history[1] == {"error": "busy"}:
                action = {1: {"op": "discover"}, 2: {"op": "start", "task": "build"},
                          3: {"op": "read", "path": "build.md", "first": 2, "last": 2},
                          4: {"op": "submit", "report": "build"},
                          5: {"op": "stop"}}[step]
                if step == 2:
                    assert [item["id"] for item in row["tasks"]] == ["build"]
                if step == 4:
                    assert row == {"first": 2, "last": 2, "lines": 3, "text": "fixture build"}
            elif step == 1:
                action = {"op": "read", "path": "secret", "first": 1, "last": 1}
            elif step == 2:
                assert row == {"error": "out_of_scope"}
                action = {"op": "read", "path": "guide.md", "first": 1, "last": 1}
            elif step == 3:
                assert row == {"first": 1, "last": 1, "lines": 1, "text": "fixture guide"}
                action = {"op": "submit", "report": "é" * 1025}
            elif step == 4:
                assert row == {"error": "invalid_report"}
                action = {"op": "submit", "report": "é" * 1024}
            else:
                assert set(row) == {"digest"}
                action = {"op": "stop"}
            return action, Usage(100, 20)

        return 200, send

    sources["build.md"] = "first\nfixture build\nthird\n"
    reports, counters, stops, traces = run_arm(base, tasks, sources, workers, prepare, ledger=ledger, credentials=credentials)
    assert all(len(rows) == 1 for rows in reports)
    assert sorted(rows[0]["task"] for rows in reports) == (["guide"] * workers if ledger is None else ["build", "guide"])
    if ledger is not None:
        events = [item["event"] for item in ledger.audit()]
        assert events.count("claimed") == events.count("submitted") == 2 and "authorized" not in events
    assert [row["requests"] for row in counters] == [6] * workers
    assert [row["tools"] for row in counters] == [5] * workers
    assert stops == ["model_stop"] * workers
    assert sorted(event["started"] for trace in traces for event in trace if "started" in event) == (
        ["guide"] * workers if ledger is None else ["build", "guide"])
    assert sum(event.get("error") == "busy" for trace in traces for event in trace) == (ledger is not None)


def test_late_ledger_receipt_is_retained_but_report_is_not_offered_for_review(tmp_path, monkeypatch):
    now = [0.0]
    base = "a" * 40
    tasks = [dict(task="guide", issue=101, title="Guide", paths=["guide.md"])]
    ledger = Pilot(tmp_path / "pilot.db")
    ledger.initialize("example/project", publication_limit=0, active_limit=2, lease_seconds=900)
    ledger.add_task(base=base, **tasks[0])
    credentials = [ledger.enroll(f"worker-{i}", f"owner-{i}", "contributor") for i in range(2)]
    submit = ledger.submit

    def late_submit(*args):
        digest = submit(*args)
        now[0] = 900.0
        return digest

    monkeypatch.setattr(ledger, "submit", late_submit)

    def prepare(worker, history):
        action = ({"op": "stop"} if worker else
                  ({"op": "start", "task": "guide"} if len(history) == 1 else {"op": "submit", "report": "fixture"}))
        return 200, lambda *_: (action, Usage(100, 20))

    reports, counters, stops, traces = gate["run_arm"](base, tasks, {"guide.md": "fixture"}, 2, prepare,
                                                       ledger=ledger, credentials=credentials, clock=lambda: now[0])
    assert reports == [[], []]
    assert stops[0] == "deadline" and counters[0]["tools"] == 2
    assert traces[0][-1] == {"op": "submit", "error": "deadline"}
    assert "submitted" in [item["event"] for item in ledger.audit()]


def test_read_ranges_fail_closed_and_count_refusals():
    errors = [
        ({"op": "read", "path": "guide.md", "first": 1, "last": 1}, "out_of_scope"),
        ({"op": "start", "task": "guide"}, None),
        ({"op": "read", "path": "guide.md", "first": True, "last": 2}, "invalid_range"),
        ({"op": "read", "path": "guide.md", "first": 1, "last": 0}, "invalid_range"),
        ({"op": "read", "path": "guide.md", "first": 1, "last": 129}, "invalid_range"),
        ({"op": "read", "path": "guide.md", "first": 3, "last": 3}, "invalid_range"),
        ({"op": "read", "path": "guide.md", "first": 2, "last": 2}, "read_too_large"),
        ({"op": "stop"}, None),
    ]

    def prepare(worker, history):
        step = len(history) - 1
        if step and errors[step - 1][1]:
            assert history[-1]["error"] == errors[step - 1][1]
            if errors[step - 1][1] == "invalid_range":
                assert history[-1]["lines"] == 2
        return 200, lambda *_: (errors[step][0], Usage(100, 20))

    tasks = [dict(task="guide", paths=["guide.md"])]
    reports, counters, stops, _ = gate["run_arm"]("a" * 40, tasks, {"guide.md": "first\n" + "é" * 4097}, 1, prepare)
    assert reports == [[]] and stops == ["model_stop"]
    assert counters[0]["tools"] == 7


def test_runner_preserves_partial_reports_when_model_response_is_lost():
    actions = iter([{"op": "start", "task": "guide"}, {"op": "submit", "report": "fixture"}, None])

    def lost(*args):
        raise TimeoutError("transport lost the response")

    def prepare(worker, history):
        action = next(actions)
        return 200, (lost if action is None else lambda *_: (action, Usage(100, 20)))

    tasks = [dict(task="guide", paths=["guide.md"])]
    reports, counters, stops, traces = gate["run_arm"]("a" * 40, tasks, {"guide.md": "fixture"}, 1, prepare)
    assert reports[0][0]["report"] == "fixture"
    assert counters == [{"requests": 3, "tools": 2, "tokens": 240, "unknown": 1}]
    assert stops == ["unknown_usage"] and traces[0][-1] == {"op": "model", "error": "unknown_usage"}
