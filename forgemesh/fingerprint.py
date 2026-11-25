"""Whitespace-insensitive patch fingerprint, similar in spirit to `git patch-id --stable`."""

from __future__ import annotations

import hashlib
import re


def patch_id(diff: str) -> str:
    """Hash of the changed lines per file, ignoring hunk positions, context and whitespace."""
    files: dict[str, list[str]] = {}
    current = None
    for line in diff.splitlines():
        if line.startswith("diff --git "):
            current = line.split(" b/", 1)[-1]
            files.setdefault(current, [])
        elif current and (line.startswith("+") or line.startswith("-")) and not line.startswith(("+++", "---")):
            files[current].append(line[0] + re.sub(r"\s+", "", line[1:]))
    h = hashlib.sha256()
    for name in sorted(files):
        h.update(name.encode() + b"\0" + "\n".join(files[name]).encode() + b"\0")
    return h.hexdigest()
