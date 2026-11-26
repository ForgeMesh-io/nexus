import asyncio
import os
from pathlib import Path
from select import select
import subprocess
import sys

import pytest

from forgemesh.pilot import Pilot

mcp = pytest.importorskip("mcp")
BWRAP = pytest.mark.skipif(os.environ.get("NEXUS_TEST_BWRAP") != "1", reason="opt-in Linux OS boundary test")


def bridge_command(ledger_path, isolated, *bridge_args):
    """Bridge command; isolated runs it as UID 65534 in Bubblewrap and asserts the ledger is invisible."""
    if not isolated:
        return [sys.executable, "-m", "forgemesh.pilot_mcp", *bridge_args]
    venv = Path(sys.prefix)
    base = Path(sys.base_prefix)
    assert venv != base and "/site-packages/" in str(mcp.__file__)
    return ["bwrap", "--unshare-user", "--uid", "65534", "--gid", "65534", "--unshare-pid", "--die-with-parent",
            "--dev", "/dev", "--proc", "/proc", "--tmpfs", "/tmp", "--chdir", "/tmp"] + [
                arg for path in ("/usr", "/lib", "/lib64", str(venv), str(base)) if Path(path).exists()
                for arg in ("--ro-bind", path, path)
            ] + [sys.executable, "-c", (
                "import os,sys; from forgemesh.pilot_mcp import main; "
                "assert os.getuid() == 65534 and not os.path.lexists(sys.argv.pop(1)); main()"
            ), str(ledger_path), *bridge_args]


@pytest.mark.parametrize("isolated", [False, pytest.param(True, marks=BWRAP)])
def test_stdio_session_can_only_use_participant_api(tmp_path, isolated):
    ledger = Pilot(tmp_path / "pilot.db")
    ledger.initialize("example/project")
    writer = ledger.enroll("writer", "alice", "contributor")
    reviewer = ledger.enroll("reviewer", "bob", "reviewer")
    maintainer = ledger.enroll("maintainer", "carol", "maintainer")
    ledger.add_task("guide", 7, "b" * 40, "Check the guide")

    def connection(token, port):
        command, *args = bridge_command(ledger.path, isolated, str(port))
        return mcp.Client(mcp.StdioServerParameters(
            command=command, args=args,
            env={"NEXUS_PARTICIPANT_TOKEN": token},
        ))

    async def exercise(port):
        async with connection(writer, port) as client:
            tools = await client.list_tools()
            assert {tool.name for tool in tools.tools} == {"discover", "claim", "submit", "review"}
            assert all("token" not in tool.input_schema.get("properties", {}) for tool in tools.tools)
            result = await client.call_tool("discover", {})
            assert not result.is_error, result.content
            assert result.structured_content is not None, result.content
            assert result.structured_content["tasks"][0]["id"] == "guide"
            result = await client.call_tool("claim", {"task": "guide"})
            lease = result.structured_content["lease"]
            result = await client.call_tool("submit", {"task": "guide", "lease": lease, "report": "Missing step"})
            digest = result.structured_content["digest"]
            args = {"task": "guide", "digest": digest, "verdict": "pass", "evidence": "Checked"}
            denied = await client.call_tool("review", args)
            assert denied.is_error and "unauthorized" in denied.content[0].text
        async with connection(reviewer, port) as client:
            result = await client.call_tool("review", args)
            assert result.structured_content == {"status": "validated"}
        ledger.revoke(maintainer, "writer")
        async with connection(writer, port) as client:
            denied = await client.call_tool("discover", {})
            assert denied.is_error and "unauthorized" in denied.content[0].text

    with subprocess.Popen([sys.executable, "-m", "forgemesh.pilot_http", str(ledger.path), "--port", "0"],
                          stdout=subprocess.PIPE, text=True) as process:
        try:
            assert select([process.stdout], [], [], 5)[0], "participant API did not start"
            url = process.stdout.readline().strip()
            assert url.startswith("http://127.0.0.1:"), url
            asyncio.run(asyncio.wait_for(exercise(int(url.rsplit(":", 1)[1])), timeout=15))
        finally:
            process.terminate()


@pytest.mark.parametrize("isolated", [False, pytest.param(True, marks=BWRAP)])
def test_streamable_http_bridge_is_loopback_and_uses_each_callers_token(tmp_path, isolated):
    import socket
    import time
    from urllib.error import HTTPError
    from urllib.request import Request, urlopen

    from mcp.client.streamable_http import streamable_http_client
    from mcp.shared._httpx_utils import create_mcp_http_client

    ledger = Pilot(tmp_path / "pilot.db")
    ledger.initialize("example/project")
    writer = ledger.enroll("writer", "alice", "contributor")
    maintainer = ledger.enroll("maintainer", "carol", "maintainer")
    ledger.add_task("guide", 7, "b" * 40, "Check the guide")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    url = f"http://127.0.0.1:{port}/mcp"

    def client(token=None):
        headers = {"Authorization": "Bearer " + token} if token else {}
        return mcp.Client(streamable_http_client(url, http_client=create_mcp_http_client(headers=headers)))

    async def exercise():
        async with client(writer) as session:
            assert {tool.name for tool in (await session.list_tools()).tools} == {
                "discover", "claim", "submit", "review"}
            assert (await session.call_tool("discover", {})).structured_content["tasks"][0]["id"] == "guide"
            assert (await session.call_tool("claim", {"task": "guide"})).structured_content == {"lease": 1}
        async with client() as session:
            denied = await session.call_tool("discover", {})
            assert denied.is_error and "unauthorized" in denied.content[0].text
        ledger.revoke(maintainer, "writer")
        async with client(writer) as session:
            denied = await session.call_tool("discover", {})
            assert denied.is_error and "unauthorized" in denied.content[0].text

    def status(headers):
        request = Request(url, b"{}", {"Content-Type": "application/json",
                                       "Accept": "application/json, text/event-stream"} | headers)
        try:
            with urlopen(request, timeout=5) as response:
                return response.status
        except HTTPError as error:
            return error.code

    with subprocess.Popen([sys.executable, "-m", "forgemesh.pilot_http", str(ledger.path), "--port", "0"],
                          stdout=subprocess.PIPE, text=True) as api:
        try:
            assert select([api.stdout], [], [], 5)[0], "participant API did not start"
            api_port = api.stdout.readline().strip().rsplit(":", 1)[1]
            with subprocess.Popen(bridge_command(ledger.path, isolated, api_port, "--http", str(port)),
                                  env={"PATH": os.environ["PATH"]}, stderr=subprocess.PIPE) as bridge:
                try:
                    for _ in range(100):
                        with socket.socket() as attempt:
                            if attempt.connect_ex(("127.0.0.1", port)) == 0:
                                break
                        time.sleep(0.05)
                    assert status({"Host": "nexus.example"}) == 421
                    assert status({"Origin": "https://evil.example"}) == 403
                    asyncio.run(asyncio.wait_for(exercise(), timeout=15))
                finally:
                    bridge.terminate()
            assert [event["event"] for event in ledger.audit()].count("claimed") == 1
        finally:
            api.terminate()
