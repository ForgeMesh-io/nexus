"""Characterize OpenCode 2.0.21 with a scripted provider; never forward requests."""

import json
import os
import pty
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from select import select
from subprocess import PIPE, Popen, check_output
import sys
from tempfile import TemporaryDirectory
from threading import Barrier, Thread
from time import monotonic, sleep

from forgemesh.pilot import Pilot


@contextmanager
def participant_api(root, enabled):
    if not enabled:
        yield [], ()
        return
    ledger = Pilot(root / "pilot.db")
    ledger.initialize("example/project", publication_limit=0)
    ledger.add_task("guide", 101, "b" * 40, "Synthetic task")
    credentials = [ledger.enroll(f"worker-{i}", f"owner-{i}", "contributor") for i in range(2)]
    with Popen([sys.executable, "-m", "forgemesh.pilot_http", str(ledger.path), "--port", "0"],
               stdout=PIPE, text=True) as api:
        try:
            assert select([api.stdout], [], [], 5)[0], "participant API did not start"
            url = api.stdout.readline().strip()
            assert url.startswith("http://127.0.0.1:"), url
            yield [sys.executable, "-m", "forgemesh.pilot_mcp", url.rsplit(":", 1)[1]], credentials
        finally:
            api.terminate()


def probe(root, arm, workers):
    root.mkdir()
    steps = 12 // workers
    tool_name = "nexus_discover" if arm == "nexus" else "read"
    seen = [[] for _ in range(workers)]
    deadlines = [None] * workers
    opened = Barrier(workers, timeout=20)

    class Fixture(BaseHTTPRequestHandler):
        def do_POST(self):
            worker, rest = self.path.lstrip("/").split("/", 1)
            i = int(worker)
            assert rest == "v1/chat/completions"
            events = seen[i]
            data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            assert data["model"] == "stub"
            tools = {t["function"]["name"] for t in data.get("tools", [])}
            results = [m["content"] for m in data["messages"] if m["role"] == "tool"]
            assert all(("guide" if arm == "nexus" else "Fixture line.") in str(result) for result in results), results
            final = any("MAXIMUM STEPS REACHED" in str(m.get("content")) for m in data["messages"])
            primary = tool_name in tools or final
            n = sum(e[0] for e in events) + 1
            events.append((primary, len(results), data.get("max_completion_tokens"),
                           data.get("stream_options", {}).get("include_usage"), final))
            if primary and n == 1:
                opened.wait()  # Both real OpenCode clients must reach the backend concurrently.
            if primary and n == steps:
                assert final
                self.send_response(429)
                self.send_header("Retry-After", "1")
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"error":{"message":"synthetic rate limit"}}')
                return
            if primary and n > steps:
                deadlines[i] = monotonic() + 0.25  # External observation cutoff, not a host setting.
                sleep(0.6)
            delta = {"content": "Late fixture response." if final else "Fixture title."}
            if primary and not final:
                delta = {"tool_calls": [{"index": i, "id": f"call_{n}_{i}", "type": "function", "function": {
                    "name": tool_name, "arguments": json.dumps({} if arm == "nexus" else {
                        "path": str(root / worker / "fixture.txt"), "offset": (n - 1) * 3 + i + 1, "limit": 1,
                    })}} for i in range(3)]}
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            chunk = {"id": "fixture", "object": "chat.completion.chunk", "created": 0, "model": "stub"}
            chunks = [
                {"choices": [{"index": 0, "delta": {"role": "assistant"} | delta}]},
                {"choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls" if "tool_calls" in delta else "stop"}]},
            ]
            if not (primary and n == 1):  # No usage for the first successful tool turn.
                chunks.append({"choices": [], "usage": {"prompt_tokens": 8000, "completion_tokens": 20,
                    "total_tokens": 8020, "prompt_tokens_details": {"cached_tokens": 6000},
                    "completion_tokens_details": {"reasoning_tokens": 10}}})
            for payload in chunks:
                self.wfile.write(b"data: " + json.dumps(chunk | payload).encode() + b"\n\n")
            self.wfile.write(b"data: [DONE]\n\n")

        def log_message(self, *args):
            pass

    with (participant_api(root, arm == "nexus") as (command, credentials),
          ThreadingHTTPServer(("127.0.0.1", 0), Fixture) as server,
          ThreadPoolExecutor(max_workers=workers) as clients):
        Thread(target=server.serve_forever, daemon=True).start()

        def session(i):
            cwd = root / str(i)
            cwd.mkdir()
            (cwd / "home").mkdir()
            (cwd / "fixture.txt").write_text("Fixture line.\n" * 40)
            env = {"HOME": str(cwd / "home"), "PATH": os.environ["PATH"], "FIXTURE_API_KEY": "fixture",
                   "TERM": "xterm-256color"}
            config = {"model": "fixture/stub", "default_agent": "trial", "compaction": {"auto": False},
                      "agents": {"trial": {"steps": steps}},
                      "permissions": [{"action": "*", "resource": "*", "effect": "deny"},
                                      {"action": tool_name, "resource": "*", "effect": "allow"}],
                      "providers": {"fixture": {"name": "Fixture", "env": ["FIXTURE_API_KEY"],
                       "package": "@opencode/ai/providers/openai-compatible",
                       "settings": {"baseURL": f"http://127.0.0.1:{server.server_port}/{i}/v1"},
                       "models": {"stub": {"limit": {"context": 16000, "output": 32}}}}}}
            if command:
                env["NEXUS_PARTICIPANT_TOKEN"] = credentials[i]
                config["mcp"] = {"servers": {"nexus": {"type": "local", "command": command, "codemode": False,
                    "environment": {"NEXUS_PARTICIPANT_TOKEN": "{env:NEXUS_PARTICIPANT_TOKEN}"}}}}
            (cwd / "opencode.json").write_text(json.dumps(config))
            master, terminal = pty.openpty()
            try:
                with Popen(["opencode", "--standalone", "--auto", "--prompt", "Run the metering fixture."],
                           cwd=cwd, env=env, stdin=terminal, stdout=terminal, stderr=terminal) as process:
                    try:
                        end = monotonic() + 30
                        output = b""
                        while monotonic() < end and select([master], [], [], max(0, end - monotonic()))[0]:
                            output += os.read(master, 65536)
                            if b"Late fixture response." in output:
                                assert deadlines[i] is not None and monotonic() >= deadlines[i]
                                return
                        raise AssertionError(output[-3000:])
                    finally:
                        process.terminate()
            finally:
                os.close(master)
                os.close(terminal)

        try:
            list(clients.map(session, range(workers)))
        finally:
            server.shutdown()
    attempts = sum(sum(e[0] for e in events) for events in seen)
    tool_results = sum(max(e[1] for e in events) for events in seen)
    continued = sum(sum(e[0] for e in events) > 1 for events in seen)
    known_tokens = (attempts - 2 * workers) * 8020  # First turn and 429 have no usage; exclude titles.
    assert attempts > 12 and tool_results > 24, seen
    assert continued == workers and known_tokens > 64000, seen
    assert all(events[-1][2:] == (32, True, True) for events in seen), seen
    print(f"{arm}: HTTP attempts={sum(map(len, seen))}/12 ({attempts} primary), tool results={tool_results}/24, "
          f"reported primary tokens >= {known_tokens}/64000, continued after missing usage={continued}, "
          f"late outputs rendered={workers}", flush=True)


if __name__ == "__main__":
    version = check_output(["opencode", "--version"], text=True).strip()
    if version != "opencode v2.0.21":
        raise SystemExit(f"This fixture characterizes OpenCode v2.0.21, not {version}.")
    print(version, flush=True)
    with TemporaryDirectory(dir=os.environ.get("TMPDIR")) as scratch:
        for arm, count in (("solo", 1), ("independent", 2), ("nexus", 2)):
            probe(Path(scratch) / arm, arm, count)
