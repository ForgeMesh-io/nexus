"""End-to-end: `python -m forgemesh verify` against a registry served over real HTTP (localhost)."""

import functools
import http.server
import json
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from forgemesh import registry as reg

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = {"swarm": "nexus", "codename": "NEXUS", "protocol": 1, "status": "alpha",
            "repository": "https://github.com/ForgeMesh-io/nexus", "description": "ForgeMesh core",
            "instructions": "AGENTS.md", "nexus_ref": "0" * 40,
            "images": {"nexus": "ghcr.io/forgemesh-io/nexus@sha256:" + "1" * 64}}


@pytest.fixture
def served(tmp_path):
    server_dir = tmp_path / "site"
    anchor = reg.init_dev(server_dir, tmp_path / "keys", ["nexus"])
    repo, kr = reg.Repo(server_dir), reg.Keyring(tmp_path / "keys")
    repo.add_target("nexus", "manifest.json", reg.dumps_manifest(MANIFEST), [kr.get("DEV-swarm-nexus")])
    repo.refresh(kr.get("DEV-snapshot"), kr.get("DEV-timestamp"))
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(server_dir))
    handler.log_message = lambda *a: None
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_port}", anchor, tmp_path
    httpd.shutdown()


def verify(url, anchor, cache, swarm="nexus"):
    return subprocess.run([sys.executable, "-m", "forgemesh", "verify", "--registry", url, "--anchor", anchor,
                           "--swarm", swarm, "--cache", str(cache)], capture_output=True, text=True, cwd=ROOT)


def test_verify_ok(served):
    url, anchor, tmp = served
    r = verify(url, anchor, tmp / "cache")
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["codename"] == "NEXUS"


def test_verify_wrong_anchor(served):
    url, _, tmp = served
    r = verify(url, "f" * 64, tmp / "cache")
    assert r.returncode == 3 and "trust anchor mismatch" in r.stderr


def test_verify_unknown_swarm(served):
    url, anchor, tmp = served
    r = verify(url, anchor, tmp / "cache", swarm="vie")
    assert r.returncode == 3
