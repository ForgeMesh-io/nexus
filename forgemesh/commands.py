"""Strict parser for coordination commands posted as GitHub comments.

Only lines starting with ``/fm`` are considered; everything else in a comment is
ignored and never interpreted. Comment text is untrusted input.
"""

from __future__ import annotations

import re

TASK = r"(?P<task>[A-Z][A-Z0-9]{1,15}-[0-9]{4,})"
SHA = r"(?P<sha>[0-9a-fA-F]{7,64})"
URL = r"(?P<evidence>https://\S{1,500})"
PATTERNS = {
    "claim": rf"claim {TASK}",
    "start": rf"start {TASK}",
    "renew": rf"renew {TASK}",
    "release": rf"release {TASK}",
    "submit": rf"submit {TASK} #(?P<pr>[0-9]{{1,9}})",
    "vote": rf"vote {TASK} (?P<verdict>pass|fail) {SHA} {URL}",
    "approve": rf"approve {TASK} {SHA}",
    "block": rf"block {TASK} (?P<reason>.{{5,300}})",
    "unblock": rf"unblock {TASK}",
    "reopen": rf"reopen {TASK}",
    "reject": rf"reject {TASK}(?: (?P<reason>.{{1,300}}))?",
    "cancel": rf"cancel {TASK}(?: (?P<reason>.{{1,300}}))?",
}
COMPILED = {k: re.compile(rf"^/fm {v}\s*$") for k, v in PATTERNS.items()}
MAX_COMMANDS_PER_COMMENT = 5

HELP = "\n".join(f"/fm {re.sub(r'\(\?P<(\w+)>[^)]*\)\??', r'<\1>', v).replace('#', '#')}" for v in PATTERNS.values())


def parse(body: str) -> list[dict]:
    """Return the commands found in a comment, in order. Unknown /fm lines yield an 'invalid' entry."""
    out = []
    for line in body.replace("\r\n", "\n").split("\n"):
        line = line.strip()
        if not line.startswith("/fm ") and line != "/fm":
            continue
        if len(out) >= MAX_COMMANDS_PER_COMMENT:
            break
        for kind, rx in COMPILED.items():
            m = rx.match(line)
            if m:
                args = {k: v for k, v in m.groupdict().items() if v is not None}
                if "pr" in args:
                    args["pr"] = int(args["pr"])
                if "sha" in args:
                    args["sha"] = args["sha"].lower()
                out.append({"kind": kind, **args})
                break
        else:
            out.append({"kind": "invalid", "line": line[:200]})
    return out
