from concurrent.futures import ThreadPoolExecutor
import json
import shutil
import socket
import subprocess
import sys
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from forgemesh.pilot import Pilot


@pytest.fixture
def service(tmp_path):
    ledger = Pilot(tmp_path / "pilot.db")
    ledger.initialize("example/project")
    writer = ledger.enroll("writer", "alice", "contributor")
    reviewer = ledger.enroll("reviewer", "bob", "reviewer")
    maintainer = ledger.enroll("maintainer", "carol", "maintainer")
    ledger.add_task("guide", 7, "b" * 40, "Check the guide")
    with subprocess.Popen([sys.executable, "-m", "forgemesh.pilot_http", str(ledger.path),
                           "--port", "0"], stdout=subprocess.PIPE, text=True) as process:
        try:
            url = process.stdout.readline().strip()
            assert url.startswith("http://127.0.0.1:"), url
            yield url, ledger, writer, reviewer, maintainer
        finally:
            process.terminate()


def request(url, action, token, payload=None, headers=None):
    req = Request(f"{url}/v1/{action}", data=json.dumps(payload or {}).encode(), headers={
        "Authorization": "Bearer " + token, "Content-Type": "application/json", **(headers or {}),
    })
    try:
        response = urlopen(req, timeout=5)
    except HTTPError as exc:
        response = exc
    with response:
        return response.code, json.load(response)


def test_python_client_can_contribute_and_operator_can_revoke(service):
    url, ledger, writer, reviewer, maintainer = service
    assert request(url, "discover", writer)[1]["tasks"][0]["id"] == "guide"
    assert request(url, "claim", writer, {"task": "guide"}) == (200, 1)
    code, digest = request(url, "submit", writer, {"task": "guide", "lease": 1, "report": "Observed missing step"})
    assert code == 200
    assert request(url, "review", reviewer, {"task": "guide", "digest": digest,
                                              "verdict": "pass", "evidence": "Checked"}) == (200, "validated")
    assert request(url, "authorize", maintainer, {"task": "guide", "digest": digest}) == (404, {"error": "unknown_action"})
    ledger.revoke(maintainer, "writer")
    assert request(url, "discover", writer) == (401, {"error": "unauthorized"})
    ledger.stop(maintainer)
    assert request(url, "discover", reviewer) == (409, {"error": "stopped"})


def test_participant_gateway_has_no_operator_routes_or_browser_origin(service):
    url, _, writer, _, maintainer = service
    for action in ("audit", "publish-local", "publish-github", "enroll", "revoke"):
        assert request(url, action, maintainer) == (404, {"error": "unknown_action"})
    assert request(url, "discover", writer, headers={"Origin": "https://other.invalid"}) == (403, {"error": "invalid_origin"})
    assert request(url, "discover", writer, headers={"Host": "other.invalid"}) == (403, {"error": "invalid_origin"})
    assert request(url, "discover", writer, {"token": maintainer}) == (400, {"error": "invalid_input"})


def test_http_backpressure_preserves_existing_reservation(service):
    url, ledger, writer, _, _ = service
    ledger.add_task("second", 8, "b" * 40, "Check another guide")
    assert request(url, "claim", writer, {"task": "guide"}) == (200, 1)
    with ThreadPoolExecutor(max_workers=8) as workers:
        results = list(workers.map(lambda _: request(url, "claim", writer, {"task": "second"}), range(24)))
    assert results == [(429, {"error": "capacity"})] * 24
    assert request(url, "claim", writer, {"task": "guide"}) == (200, 1)
    assert [event["task"] for event in ledger.audit() if event["event"] == "claimed"] == ["guide"]


def test_http_rejects_unbounded_and_ambiguous_input_without_writing(service):
    url, ledger, writer, _, _ = service
    assert request(url, "submit", writer, {"report": "a" * 65_536}) == (413, {"error": "invalid_input"})
    host, port = url.removeprefix("http://").split(":")
    with socket.create_connection((host, int(port)), timeout=5) as connection:
        connection.sendall((f"POST /v1/claim HTTP/1.1\r\nHost: {host}:{port}\r\n"
                            f"Authorization: Bearer {writer}\r\nContent-Type: application/json\r\n"
                            "Content-Length: 16\r\nContent-Length: 16\r\n\r\n").encode())
        with connection.makefile("rb") as response:
            assert response.readline().startswith(b"HTTP/1.0 400 ")
    assert not any(event["event"] == "claimed" for event in ledger.audit())
    assert request(url, "discover", writer)[0] == 200


@pytest.mark.skipif(not shutil.which("curl"), reason="curl is unavailable")
def test_curl_connects_to_the_same_discovery_contract(service):
    url, _, writer, _, _ = service
    process = subprocess.run(["curl", "-fsS", "--max-time", "5", "--config", "-", f"{url}/v1/discover"],
                             input=f'header = "Authorization: Bearer {writer}"\nheader = "Content-Type: application/json"\ndata = "{{}}"\n',
                             text=True, capture_output=True, check=True, timeout=10)
    assert json.loads(process.stdout)["repository"] == "example/project"
