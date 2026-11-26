import asyncio
import os
from pathlib import Path
from select import select
import subprocess
import sys

import pytest

from forgemesh.pilot import Pilot

mcp = pytest.importorskip("mcp")


@pytest.mark.parametrize("isolated", [False, pytest.param(True, marks=pytest.mark.skipif(
    os.environ.get("NEXUS_TEST_BWRAP") != "1", reason="opt-in Linux OS boundary test"))])
def test_stdio_session_can_only_use_participant_api(tmp_path, isolated):
    ledger = Pilot(tmp_path / "pilot.db")
    ledger.initialize("example/project")
    writer = ledger.enroll("writer", "alice", "contributor")
    reviewer = ledger.enroll("reviewer", "bob", "reviewer")
    maintainer = ledger.enroll("maintainer", "carol", "maintainer")
    ledger.add_task("guide", 7, "b" * 40, "Check the guide")

    def connection(token, port):
        command = sys.executable
        args = ["-m", "forgemesh.pilot_mcp", str(port)]
        if isolated:
            venv = Path(sys.prefix)
            base = Path(sys.base_prefix)
            assert venv != base and "/site-packages/" in str(mcp.__file__)
            command = "bwrap"
            args = ["--unshare-user", "--uid", "65534", "--gid", "65534", "--unshare-pid", "--die-with-parent",
                    "--dev", "/dev", "--proc", "/proc",
                    "--tmpfs", "/tmp", "--chdir", "/tmp"] + [
                        arg for path in ("/usr", "/lib", "/lib64", str(venv), str(base)) if Path(path).exists()
                        for arg in ("--ro-bind", path, path)
                    ] + [sys.executable, "-c", (
                        "import os,sys; from forgemesh.pilot_mcp import main; "
                        "assert os.getuid() == 65534 and not os.path.lexists(sys.argv.pop(1)); main()"
                    ), str(ledger.path), str(port)]
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
