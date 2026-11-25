"""Append-only journal stored on a Git branch, with compare-and-swap writes.

Layout of the state branch:
    journal.jsonl   one event per line, append-only (canonical order)
    state.json      fold(journal) — derived, rewritten on every commit
    decisions.jsonl one decision per request event — derived
    cursor.json     ingestion cursor for the GitHub inbox

Correctness argument: every writer appends to the journal it fetched and pushes
without force. Git rejects any push that is not a fast-forward, so two writers
can never both publish different continuations of the same journal. The loser
re-fetches, re-applies its new inputs on top (deduplicated by event id) and
retries. The decisions of the winner are therefore never contradicted.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime
from pathlib import Path

from .core import fold

BRANCH = "forgemesh-state"


class PushRejected(Exception):
    pass


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=check)


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def dumps(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class Store:
    """A local clone of the state branch."""

    def __init__(self, workdir: Path, remote: str = "origin", branch: str = BRANCH):
        self.dir, self.remote, self.branch = Path(workdir), remote, branch

    # -- reading ---------------------------------------------------------
    def sync(self) -> None:
        """Make the working tree equal to the remote branch (or empty if it does not exist yet)."""
        # ls-remote exit code 2 = ref absent (locale-independent, unlike parsing fetch errors)
        probe = _git(self.dir, "ls-remote", "--exit-code", "--heads", self.remote, self.branch, check=False)
        if probe.returncode == 2:
            _git(self.dir, "checkout", "--quiet", "--orphan", self.branch, check=False)
            _git(self.dir, "rm", "-rq", "--cached", ".", check=False)
            for p in ("journal.jsonl", "state.json", "decisions.jsonl", "cursor.json"):
                (self.dir / p).unlink(missing_ok=True)
            return
        r = _git(self.dir, "fetch", "--quiet", self.remote, self.branch, check=False)
        if probe.returncode != 0 or r.returncode != 0:
            raise RuntimeError(f"git fetch failed: {(probe.stderr or r.stderr).strip()}")
        _git(self.dir, "checkout", "--quiet", "-f", "-B", self.branch, "FETCH_HEAD")
        _git(self.dir, "reset", "--quiet", "--hard", "FETCH_HEAD")

    def events(self) -> list[dict]:
        return read_jsonl(self.dir / "journal.jsonl")

    def cursor(self) -> dict:
        p = self.dir / "cursor.json"
        return json.loads(p.read_text()) if p.exists() else {}

    # -- writing ---------------------------------------------------------
    def write(self, events: list[dict], cursor: dict, now: datetime, message: str) -> None:
        journal = self.dir / "journal.jsonl"
        old = self.events()
        if events[: len(old)] != old:
            raise AssertionError("journal is append-only")
        journal.write_text("".join(dumps(e) + "\n" for e in events))
        state = fold(events, until=now)
        (self.dir / "state.json").write_text(json.dumps({"version": 1, **state.to_json()}, indent=1, sort_keys=True) + "\n")
        (self.dir / "decisions.jsonl").write_text("".join(dumps(d) + "\n" for d in state.decisions))
        (self.dir / "cursor.json").write_text(json.dumps(cursor, indent=1, sort_keys=True) + "\n")
        _git(self.dir, "add", "journal.jsonl", "state.json", "decisions.jsonl", "cursor.json")
        if _git(self.dir, "diff", "--cached", "--quiet", check=False).returncode == 0:
            return
        _git(self.dir, "-c", "user.name=forgemesh-coordinator", "-c", "user.email=forgemesh@users.noreply.github.com",
             "commit", "--quiet", "-m", message)
        r = _git(self.dir, "push", "--quiet", self.remote, f"HEAD:refs/heads/{self.branch}", check=False)
        if r.returncode != 0:
            raise PushRejected(r.stderr.strip())


def merge_new(events: list[dict], incoming: list[dict]) -> list[dict]:
    """Append incoming events that are not already in the journal, preserving their order."""
    seen = {e["id"] for e in events}
    out = list(events)
    for e in incoming:
        if e["id"] not in seen:
            seen.add(e["id"])
            out.append(e)
    return out
