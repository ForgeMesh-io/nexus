"""In-memory admission gate for the offline three-arm rehearsal, not a provider adapter."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from hashlib import sha256
from threading import Event, Lock
from time import monotonic

from forgemesh.pilot import PilotError


class Refused(Exception):
    pass


@dataclass(frozen=True)
class Usage:
    input: int  # Inclusive of cached input.
    output: int  # Inclusive of reasoning output.
    cached: int = 0
    reasoning: int = 0

    def total(self):
        if (any(type(n) is not int or n < 0 for n in (self.input, self.output, self.cached, self.reasoning))
                or self.cached > self.input or self.reasoning > self.output):
            return None
        return self.input + self.output


class Budget:
    """Create at launch; callbacks must honor the deadline and stop event at the transport."""

    def __init__(self, workers, *, clock=monotonic):
        if type(workers) is not int or workers not in (1, 2):
            raise ValueError("a trial arm needs one or two workers")
        self._clock = clock
        self._deadline = clock() + 900
        self._lock = Lock()
        self._stop = Event()
        self._reason = None
        self._request_limit = 12 // workers
        self._tool_limit = 24 // workers
        self._token_limit = 64000 // workers
        self._workers = [dict(requests=0, tools=0, tokens=0, unknown=0) for _ in range(workers)]
        self._pending = set()

    def _halt(self, reason):
        if self._reason is None:
            self._reason = reason
        self._stop.set()

    def _check(self):
        if self._clock() >= self._deadline:
            self._halt("deadline")
        if self._reason:
            raise Refused(self._reason)

    def cancel(self):
        with self._lock:
            self._halt("cancelled")

    def snapshot(self):
        with self._lock:
            return [state.copy() for state in self._workers]

    def _state(self, worker):
        if type(worker) is not int or not 0 <= worker < len(self._workers):
            raise ValueError("invalid worker")
        return self._workers[worker]

    def model(self, worker, bound, send):
        if type(bound) is not int or bound <= 0:
            raise ValueError("a positive integer token bound is required")
        with self._lock:
            self._check()
            state = self._state(worker)
            if worker in self._pending:
                raise Refused("in_flight")
            if state["requests"] >= self._request_limit:
                raise Refused("request_limit")
            if state["tokens"] + bound > self._token_limit:
                raise Refused("token_limit")
            state["requests"] += 1
            # One in-flight slot reserves this worker's bound; partitions never borrow.
            self._pending.add(worker)

        actual = None
        try:
            result, usage = send(self._deadline, self._stop)
            if isinstance(usage, Usage):
                actual = usage.total()
        finally:
            with self._lock:
                self._pending.remove(worker)
                if actual is None:
                    state["unknown"] += 1
                    self._halt("unknown_usage")
                else:
                    state["tokens"] += actual
                    if actual > bound:
                        self._halt("usage_over_bound")
        with self._lock:
            self._check()
        return result

    def tool(self, worker, call):
        with self._lock:
            self._check()
            state = self._state(worker)
            if state["tools"] >= self._tool_limit:
                raise Refused("tool_limit")
            state["tools"] += 1
        result = call(self._deadline, self._stop)
        with self._lock:
            self._check()
        return result


def run_arm(base, tasks, sources, workers, prepare, *, ledger=None, credentials=(), clock=monotonic):
    """Run scripted action turns. `prepare` builds a request without dispatching it."""
    if ledger is not None and (workers != 2 or len(credentials) != workers):
        raise ValueError("Nexus rehearsal requires two contributor credentials")
    lines = {path: source.split("\n") for path, source in sources.items()}
    for path, source in sources.items():
        if not source or source.endswith("\n"):
            lines[path].pop()
    scoped = {task["task"]: {path: lines[path] for path in task["paths"]} for task in tasks}

    def participant(worker):
        history = [{"base": base, "tasks": tasks}]
        reports = []
        trace = []
        completed = set()
        active = lease = None
        token = credentials[worker] if ledger is not None else None

        def dispatch(action):
            nonlocal active, lease
            op = action.get("op") if isinstance(action, dict) else None
            if op == "discover" and ledger is not None and set(action) == {"op"}:
                return ledger.discover(token)
            if op == "start" and set(action) == {"op", "task"}:
                task = action["task"]
                if not isinstance(task, str) or task not in scoped:
                    return {"error": "out_of_scope"}
                if active is not None or task in completed:
                    return {"error": "already_started"}
                lease = ledger.claim(token, task) if ledger is not None else None
                active = task
                return {"started": task}
            if op == "read" and set(action) == {"op", "path", "first", "last"}:
                path = action["path"]
                if active is None or not isinstance(path, str) or path not in scoped[active]:
                    return {"error": "out_of_scope"}
                source = scoped[active][path]
                first, last = action["first"], action["last"]
                if (type(first) is not int or type(last) is not int
                        or not 1 <= first <= last <= len(source) or last - first >= 128):
                    return {"error": "invalid_range", "lines": len(source)}
                excerpt = "\n".join(source[first - 1:last])
                if len(excerpt.encode("utf-8")) > 8192:
                    return {"error": "read_too_large"}
                return {"first": first, "last": last, "lines": len(source), "text": excerpt}
            if op == "submit" and set(action) == {"op", "report"}:
                report = action["report"]
                try:
                    content = report.encode("utf-8") if isinstance(report, str) else b""
                except UnicodeEncodeError:
                    content = b""
                if active is None or not 0 < len(content) <= 2048 or not report.strip():
                    return {"error": "invalid_report"}
                digest = (ledger.submit(token, active, lease, report) if ledger is not None
                          else sha256(content).hexdigest())
                return {"digest": digest}
            return {"error": "unknown_action"}

        op = "model"
        try:
            while True:
                op = "model"
                bound, send = prepare(worker, history)
                action = budget.model(worker, bound, send)
                if action == {"op": "stop"}:
                    return reports, "model_stop", trace
                op = action.get("op") if isinstance(action, dict) else None
                if op not in ("discover", "start", "read", "submit"):
                    op = "unknown"
                try:
                    result = budget.tool(worker, lambda *_: dispatch(action))
                except PilotError as exc:
                    result = {"error": exc.code}
                trace.append({"op": op} | {k: result[k] for k in ("started", "digest", "error") if k in result})
                if "digest" in result:
                    reports.append({"task": active, "report": action["report"], "digest": result["digest"]})
                    completed.add(active)
                    active = lease = None
                history.append(result)
        except Refused as exc:
            reason = str(exc)
        except OSError:
            reason = "unknown_usage" if op == "model" else "tool_unavailable"
        trace.append({"op": op, "error": reason})
        return reports, reason, trace

    budget = Budget(workers, clock=clock)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        outcomes = list(pool.map(participant, range(workers)))
    reports, stops, traces = map(list, zip(*outcomes))
    return reports, budget.snapshot(), stops, traces
