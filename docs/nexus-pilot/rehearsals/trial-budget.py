"""In-memory admission gate for the offline three-arm rehearsal, not a provider adapter."""

from dataclasses import dataclass
from threading import Event, Lock
from time import monotonic


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
