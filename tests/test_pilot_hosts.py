"""Opt-in acceptance against installed hosts, using no model or GitHub account."""

import json
import os
from pathlib import Path
from select import select
import shutil
import subprocess
import sys

import pytest

from forgemesh.pilot import Pilot

pytestmark = pytest.mark.skipif(os.environ.get("NEXUS_TEST_HOSTS") != "1", reason="opt-in host tests")


@pytest.fixture
def host_setup(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    work = tmp_path / "client"
    work.mkdir()
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    ledger = Pilot(state / "pilot.db")
    ledger.initialize("example/project")
    writer = ledger.enroll("writer", "alice", "contributor")
    maintainer = ledger.enroll("maintainer", "carol", "maintainer")
    ledger.add_task("guide", 7, "b" * 40, "Check the guide")
    env = {"HOME": str(home), "CODEX_HOME": str(home / "codex"), "PATH": os.environ["PATH"],
           "NEXUS_PARTICIPANT_TOKEN": writer}
    with subprocess.Popen([sys.executable, "-m", "forgemesh.pilot_http", str(ledger.path), "--port", "0"],
                          cwd=work, env={"HOME": str(home), "PATH": env["PATH"]},
                          stdout=subprocess.PIPE, text=True) as process:
        try:
            assert select([process.stdout], [], [], 5)[0], "participant API did not start"
            url = process.stdout.readline().strip()
            assert url.startswith("http://127.0.0.1:"), url
            command = [sys.executable, "-m", "forgemesh.pilot_mcp", url.rsplit(":", 1)[1]]
            yield work, env, command, ledger, maintainer
        finally:
            process.terminate()


def test_opencode_connects_and_removes_configuration(host_setup):
    import pty
    import re
    import struct
    import termios
    import time
    from fcntl import ioctl

    work, env, command, _, _ = host_setup
    binary = shutil.which("opencode")
    assert binary, "OpenCode is required for host acceptance"
    file = work / "opencode.json"
    config = {"mcp": {"servers": {"nexus": {"type": "local", "command": command, "codemode": False,
              "environment": {"NEXUS_PARTICIPANT_TOKEN": "{env:NEXUS_PARTICIPANT_TOKEN}"}}}},
              "permissions": [{"action": "nexus_submit", "resource": "*", "effect": "deny"}]}
    file.write_text(json.dumps(config))

    def screen(*expected):
        master, terminal = pty.openpty()
        try:
            ioctl(terminal, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 110, 0, 0))
            with subprocess.Popen([binary, "--standalone"], cwd=work, env=env | {"TERM": "xterm-256color"},
                                  stdin=terminal, stdout=terminal, stderr=terminal) as process:
                try:
                    end = time.monotonic() + 15
                    output = b""
                    phase = 0
                    while time.monotonic() < end and select([master], [], [], max(0, end - time.monotonic()))[0]:
                        output += re.sub(rb"\x1b\[[0-?]*[ -/]*[@-~]", b"", os.read(master, 65_536))
                        if phase == 0 and b"Build" in output:
                            os.write(master, b"/mcps\r")
                            phase = 1
                        if phase == 1 and b"/mcps " in output:
                            os.write(master, b"\r")
                            phase = 2
                        if phase == 2 and all(re.search(marker, output) for marker in expected):
                            return
                    pytest.fail(f"OpenCode did not render {expected!r}: "
                                f"{re.sub(rb' +', b' ', output)[-6000:]!r}")
                finally:
                    process.terminate()
        finally:
            os.close(master)
            os.close(terminal)

    # shortcut: v2.0.21 terminal repaint fragments; use a structured status API once it initializes this location.
    screen(rb"MCP servers +esc +Search", rb"nexus", rb"disconnect *space")
    file.write_text(json.dumps({"mcp": {"servers": {}}}))
    screen(rb"MCP servers +esc +Search +No items available")


def test_opencode_turn_calls_nexus_and_enforces_local_deny(host_setup):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import pty
    import threading
    import time

    work, env, command, ledger, _ = host_setup
    binary = shutil.which("opencode")
    assert binary, "OpenCode is required for host acceptance"
    script = iter([("nexus_discover", "{}"), ("nexus_claim", '{"task":"guide"}'),
                   ("nexus_submit", '{"task":"guide","lease":1,"report":"A report"}')])
    seen = []

    class Model(BaseHTTPRequestHandler):
        """Scripted OpenAI-compatible model: one tool call per tool result, so no paid model is used."""

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            tools = [tool["function"]["name"] for tool in body.get("tools", [])]
            results = [m["content"] for m in body.get("messages", []) if m.get("role") == "tool"]
            seen.append((tools, results))
            # The first request without tools only titles the session.
            call = next(script, None) if tools and len(results) < 3 else None
            delta = ({"tool_calls": [{"index": 0, "id": f"call_{len(results)}", "type": "function",
                                      "function": {"name": call[0], "arguments": call[1]}}]}
                     if call else {"content": "done"})
            chunks = [{"choices": [{"index": 0, "delta": {"role": "assistant"} | delta}]},
                      {"choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls" if call else "stop"}],
                       "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}]
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for chunk in chunks:
                chunk |= {"id": "c", "object": "chat.completion.chunk", "created": 0, "model": "stub"}
                self.wfile.write(b"data: " + json.dumps(chunk).encode() + b"\n\n")
            self.wfile.write(b"data: [DONE]\n\n")

        def log_message(self, *args):
            pass

    model = ThreadingHTTPServer(("127.0.0.1", 0), Model)
    threading.Thread(target=model.serve_forever, daemon=True).start()
    (work / "opencode.json").write_text(json.dumps({
        "model": "fixture/stub",
        "providers": {"fixture": {"name": "Fixture", "env": ["FIXTURE_API_KEY"],
                                  "package": "@opencode/ai/providers/openai-compatible",
                                  "settings": {"baseURL": f"http://127.0.0.1:{model.server_port}/v1"},
                                  "models": {"stub": {"name": "Stub"}}}},
        "mcp": {"servers": {"nexus": {"type": "local", "command": command, "codemode": False,
                "environment": {"NEXUS_PARTICIPANT_TOKEN": "{env:NEXUS_PARTICIPANT_TOKEN}"}}}},
        "permissions": [{"action": "nexus_submit", "resource": "*", "effect": "deny"}],
    }))
    # shortcut: `opencode run` 2.0.21 does not start MCP servers here; drive the TUI until that changes.
    master, terminal = pty.openpty()
    try:
        with subprocess.Popen([binary, "--standalone", "--auto", "--prompt", "Use Nexus."], cwd=work,
                              env=env | {"TERM": "xterm-256color", "FIXTURE_API_KEY": "fixture"},
                              stdin=terminal, stdout=terminal, stderr=terminal) as process:
            try:
                end = time.monotonic() + 45
                while time.monotonic() < end and not (seen and len(seen[-1][1]) >= 3):
                    if select([master], [], [], 0.5)[0]:
                        os.read(master, 65_536)
            finally:
                process.terminate()
    finally:
        model.shutdown()
        os.close(master)
        os.close(terminal)

    tools, results = seen[-1]
    assert len(results) == 3, seen
    assert {"nexus_discover", "nexus_claim"} <= set(tools) and "nexus_submit" not in tools
    assert json.loads(results[0])["tasks"][0]["id"] == "guide"
    assert json.loads(results[1]) == {"lease": 1}
    assert 'No tool named \\"nexus_submit\\"' in results[2] or 'No tool named "nexus_submit"' in results[2]
    events = [event["event"] for event in ledger.audit()]
    assert events.count("claimed") == 1 and "submitted" not in events


def test_codex_calls_real_tools_with_no_provider_and_honors_allowlist(host_setup):
    work, env, command, ledger, maintainer = host_setup
    binary = shutil.which("codex")
    assert binary, "Codex is required for host acceptance"
    config = Path(env["CODEX_HOME"])
    config.mkdir()
    file = config / "config.toml"
    file.write_text(
        '[mcp_servers.nexus]\ncommand = ' + json.dumps(command[0]) + '\nargs = ' + json.dumps(command[1:])
        + '\nenv_vars = ["NEXUS_PARTICIPANT_TOKEN"]\nenabled_tools = ["discover", "claim"]\n'
    )
    with subprocess.Popen([binary, "app-server", "--listen", "stdio://"], cwd=work, env=env,
                          stdin=subprocess.PIPE, stdout=subprocess.PIPE, bufsize=0) as process:
        try:
            def rpc(ident, method, **params):
                process.stdin.write(json.dumps({"id": ident, "method": method, "params": params}).encode() + b"\n")
                for _ in range(100):
                    assert select([process.stdout], [], [], 15)[0], f"Codex did not answer {method}"
                    event = json.loads(process.stdout.readline())
                    if event.get("id") == ident:
                        return event
                pytest.fail(f"too many notifications before {method}")

            assert "result" in rpc(1, "initialize", clientInfo={"name": "nexus-test", "version": "0.1"},
                                   capabilities={"experimentalApi": True})
            process.stdin.write(b'{"method":"initialized"}\n')
            thread = rpc(2, "thread/start", cwd=str(work), ephemeral=True)["result"]["thread"]["id"]
            status = rpc(3, "mcpServerStatus/list", serverName="nexus", threadId=thread)["result"]["data"]
            assert set(status[0]["tools"]) == {"discover", "claim"}
            arguments = {"server": "nexus", "threadId": thread, "tool": "discover", "arguments": {}}
            report = rpc(4, "mcpServer/tool/call", **arguments)["result"]["structuredContent"]
            assert report["tasks"][0]["id"] == "guide"
            lease = rpc(5, "mcpServer/tool/call", **(arguments | {"tool": "claim", "arguments": {"task": "guide"}}))
            assert lease["result"]["structuredContent"] == {"lease": 1}
            denied = rpc(6, "mcpServer/tool/call", **(arguments | {
                "tool": "submit", "arguments": {"task": "guide", "lease": 1, "report": "A report"},
            }))
            assert "error" in denied or denied["result"]["isError"]
            assert "submitted" not in [event["event"] for event in ledger.audit()]
            ledger.revoke(maintainer, "writer")
            rejected = rpc(7, "mcpServer/tool/call", **arguments)["result"]
            assert rejected["isError"] and "unauthorized" in rejected["content"][0]["text"]
        finally:
            process.terminate()
    file.write_text("")
    result = subprocess.run([binary, "mcp", "list", "--json"], cwd=work, env=env, capture_output=True,
                            check=True, timeout=10)
    assert json.loads(result.stdout) == []
