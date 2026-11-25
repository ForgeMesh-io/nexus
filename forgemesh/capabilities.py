"""Local capability detection. Reports coarse tags only: no serial numbers, hostnames or paths."""

from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess


def _run(*cmd: str) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def _mem_gb() -> int:
    try:
        return int(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 2**30)
    except (ValueError, OSError, AttributeError):
        return 0


def detect() -> dict:
    tags = {f"os:{platform.system().lower()}", f"arch:{platform.machine().lower()}"}
    for tool in ("git", "gh", "docker", "podman", "python3", "cmake", "ninja", "clang", "gcc", "cargo", "vulkaninfo"):
        if shutil.which(tool):
            tags.add(f"tool:{tool}")
    gpus = []
    vk = _run("vulkaninfo", "--summary") if shutil.which("vulkaninfo") else ""
    for name, driver in re.findall(r"deviceName\s*=\s*(.+?)\n.*?driverID\s*=\s*(\S+)", vk, re.S):
        if "llvmpipe" in name.lower() or "lavapipe" in driver.lower():
            continue
        gpus.append({"name": name.strip(), "driver": driver})
        tags.add("gpu:vulkan")
    if not gpus and shutil.which("lspci"):
        for line in _run("lspci").splitlines():
            if re.search(r"VGA|3D controller|Display controller", line):
                gpus.append({"name": line.split(": ", 1)[-1].strip(), "driver": None})
    for g in gpus:
        n = g["name"].lower()
        if "amd" in n or "radeon" in n or "ati" in n:
            tags.add("gpu:amd")
            if re.search(r"ellesmere|polaris|rx ?(4[6-8]0|5[5-9]0)", n):
                tags.add("gpu:gfx803")
        elif "nvidia" in n or "geforce" in n:
            tags.add("gpu:nvidia")
        elif "intel" in n:
            tags.add("gpu:intel")
        if (g.get("driver") or "").upper().endswith("RADV") or "radv" in n:
            tags.add("driver:radv")
    mem = _mem_gb()
    for threshold in (8, 16, 32, 64):
        if mem >= threshold:
            tags.add(f"ram:{threshold}g")
    cpus = os.cpu_count() or 1
    for threshold in (4, 8, 16):
        if cpus >= threshold:
            tags.add(f"cpu:{threshold}c")
    return {"tags": sorted(tags), "gpus": gpus, "cpus": cpus, "ram_gb": mem}
