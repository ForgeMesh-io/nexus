"""Run untrusted build/test commands in a locked-down container.

Defaults: no network, no capabilities, no privilege escalation, read-only root
filesystem, non-root user, CPU/memory/pids limits, and only a throw-away copy
of the workspace mounted. Never the home directory, the Docker socket or any
credential. Docker is not a hard security boundary (see THREAT_MODEL.md).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

DIGEST_REF = re.compile(r"^([a-z0-9.-]+(:[0-9]+)?/)?[a-z0-9._/-]+(:[\w.-]+)?@sha256:[0-9a-f]{64}$")
FORBIDDEN_MOUNTS = ("/var/run/docker.sock", "/run/docker.sock")


def docker_args(image: str, workspace: Path, cmd: list[str], *, cpus: float = 2, memory: str = "4g",
                pids: int = 512, network: bool = False, timeout_s: int = 3600, gpu: bool = False) -> list[str]:
    if not DIGEST_REF.match(image):
        raise ValueError("image must be pinned by digest: name@sha256:<64 hex>")
    ws = Path(workspace).resolve()
    home = Path.home().resolve()
    if ws == home or ws in home.parents or str(ws) in FORBIDDEN_MOUNTS:
        raise ValueError(f"refusing to mount {ws}")
    args = ["docker", "run", "--rm", "--init",
            "--network", "bridge" if network else "none",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--read-only", "--tmpfs", "/tmp:rw,nosuid,size=2g", "--tmpfs", "/home/forge:rw,nosuid,size=1g",
            "--user", "1000:1000", "--cpus", str(cpus), "--memory", memory, "--memory-swap", memory,
            "--pids-limit", str(pids), "--stop-timeout", "10",
            "--env", "HOME=/home/forge", "--workdir", "/work",
            "--mount", f"type=bind,src={ws},dst=/work"]
    if gpu:
        # Vulkan needs the render node only, never the whole /dev.
        args += ["--device", "/dev/dri"]
    return args + [image, "timeout", str(timeout_s), *cmd]


def run(image: str, source: Path, cmd: list[str], **kw) -> subprocess.CompletedProcess:
    """Copy ``source`` into a fresh temporary workspace and run ``cmd`` there."""
    if not shutil.which("docker"):
        raise RuntimeError("docker is not installed")
    with tempfile.TemporaryDirectory(prefix="forgemesh-ws-") as tmp:
        ws = Path(tmp) / "work"
        shutil.copytree(source, ws, symlinks=True, ignore=shutil.ignore_patterns(".git", ".venv", ".env", ".env.*", "*.pem", "*.key", "__pycache__"))
        os.chmod(ws, 0o777)  # container user 1000 must be able to write
        return subprocess.run(docker_args(image, ws, cmd, **kw), capture_output=True, text=True)
