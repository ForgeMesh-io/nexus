"""Test-result attestations (in-toto Statement v1 layout, unsigned).

A signature only proves who made a claim, not that the claim is true: these
reports are evidence for independent validators, never a substitute for them.
"""

from __future__ import annotations

import hashlib
import platform
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from . import capabilities, sandbox

PREDICATE = "https://forgemesh-io.github.io/registry/attestation/test-result/v1"
MAX_LOG = 20_000


def _scrub(text: str) -> str:
    home = str(Path.home())
    return text.replace(home, "~")[-MAX_LOG:]


def git_head(repo: Path) -> str:
    return subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()


def run(task: dict, source: Path, image: str | None, mode: str = "container") -> dict:
    source = Path(source)
    sha = git_head(source)
    results = []
    for cmd in task.get("validation", {}).get("commands", []):
        if mode == "container":
            r = sandbox.run(image, source, ["sh", "-c", cmd], gpu=task.get("profile") in ("gpu", "gameplay"))
        else:
            raise ValueError("only container mode is automated; native runs must be performed and reported by a human")
        results.append({"command": cmd, "exit_code": r.returncode, "passed": r.returncode == 0,
                        "log_sha256": hashlib.sha256((r.stdout + r.stderr).encode()).hexdigest(),
                        "log_tail": _scrub(r.stdout + r.stderr)})
    caps = capabilities.detect()
    return {
        "_type": "https://in-toto.io/Statement/v1",
        "subject": [{"name": "git-commit", "digest": {"gitCommit": sha}}],
        "predicateType": PREDICATE,
        "predicate": {
            "task": task["id"],
            "image": image,
            "mode": mode,
            "environment": {"os": platform.system(), "arch": platform.machine(), "tags": caps["tags"],
                            "gpus": [g["name"] for g in caps["gpus"]]},
            "results": results,
            "passed": bool(results) and all(r["passed"] for r in results),
            "finished_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
    }
