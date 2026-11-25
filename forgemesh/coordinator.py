"""Coordinator: turns the GitHub inbox into journal events, publishes state and replies.

Runs inside a trusted GitHub Actions workflow of the swarm repository (on comment
events and on a schedule). It is stateless between runs: everything it needs is
on the state branch. Any number of runs may execute concurrently; the Git
compare-and-swap in ``journal.Store`` serialises them.
"""

from __future__ import annotations

import fnmatch
from datetime import datetime, timedelta, timezone

from . import commands
from .config import config_events
from .core import IN_REVIEW, STATES, SYSTEM, fmt_time, fold, parse_time
from .fingerprint import patch_id
from .journal import PushRejected, Store, merge_new

LOOKBACK = timedelta(minutes=10)   # re-read recent comments: covers clock skew between runs
MAX_ATTEMPTS = 8
TASK_LABEL = "fm:task"


def protected_violations(files: list[str], protected: list[str]) -> list[str]:
    return sorted({f for f in files for g in protected if fnmatch.fnmatchcase(f, g)})


class Coordinator:
    def __init__(self, gh, store: Store, policy: dict, tasks: list[dict], now=None):
        self.gh, self.store, self.policy, self.tasks = gh, store, policy, tasks
        self.now = now or (lambda: datetime.now(timezone.utc))

    # -- inbox -> events --------------------------------------------------
    def _submission(self, actor: str, pr_number: int) -> dict:
        try:
            pr = self.gh.pull(pr_number)
        except Exception:
            return {"error": f"pull request #{pr_number} not found"}
        if pr.get("state") != "open":
            return {"error": f"pull request #{pr_number} is not open"}
        files = [f["filename"] for f in self.gh.pull_files(pr_number)]
        return {
            "pr": pr_number, "head_sha": pr["head"]["sha"], "author": pr["user"]["login"],
            "patch_id": patch_id(self.gh.pull_diff(pr_number)),
            "violations": protected_violations(files, self.policy.get("protected_paths", [])),
        }

    def comment_events(self, since: str | None, known: set[str]) -> tuple[list[dict], str | None]:
        events, newest = [], since
        for c in self.gh.issue_comments_since(since):
            newest = max(newest or c["created_at"], c["created_at"])
            login = c["user"]["login"]
            if c["user"].get("type") == "Bot" or "/fm" not in c.get("body", ""):
                continue
            issue = int(c["issue_url"].rsplit("/", 1)[-1])
            for i, cmd in enumerate(commands.parse(c["body"])):
                eid = f"c:{c['id']}:{i}"
                if eid in known:
                    continue
                ev = {"id": eid, "time": c["created_at"], "actor": login, "issue": issue, "url": c.get("html_url")}
                if cmd["kind"] == "invalid":
                    ev.update(kind="invalid", task=None, line=cmd["line"])
                elif cmd["kind"] == "submit":
                    ev.update(kind="submit", task=cmd["task"], submission=self._submission(login, cmd["pr"]))
                else:
                    ev.update(cmd)
                events.append(ev)
        return events, newest

    def pr_events(self, events: list[dict], now: str) -> list[dict]:
        """Detect merges, closes and new pushes for submissions under review."""
        state = fold(events)
        out = []
        for t in state.tasks.values():
            if t.status not in IN_REVIEW or not t.submission:
                continue
            n = t.submission["pr"]
            try:
                pr = self.gh.pull(n)
            except Exception:
                continue
            base = {"actor": SYSTEM, "time": now, "task": t.id, "pr": n}
            if pr.get("merged"):
                out.append({**base, "id": f"pr:{n}:merged", "kind": "merged", "head_sha": pr["head"]["sha"]})
            elif pr.get("state") == "closed":
                out.append({**base, "id": f"pr:{n}:closed:{t.submission['head_sha']}", "kind": "pr_closed"})
            elif pr["head"]["sha"] != t.submission["head_sha"]:
                files = [f["filename"] for f in self.gh.pull_files(n)]
                out.append({**base, "id": f"pr:{n}:head:{pr['head']['sha']}", "kind": "pr_updated",
                            "head_sha": pr["head"]["sha"], "patch_id": patch_id(self.gh.pull_diff(n)),
                            "violations": protected_violations(files, self.policy.get("protected_paths", []))})
        return out

    # -- one full cycle ---------------------------------------------------
    def run(self, full_scan: bool = False) -> dict:
        for attempt in range(MAX_ATTEMPTS):
            self.store.sync()
            journal, cursor = self.store.events(), self.store.cursor()
            now = self.now()
            nows = fmt_time(now)
            since = None if full_scan or not cursor.get("comments_since") else \
                fmt_time(parse_time(cursor["comments_since"]) - LOOKBACK)
            new = config_events(self.policy, self.tasks, journal, nows)
            events = merge_new(journal, new)
            inbox, newest = self.comment_events(since, {e["id"] for e in events})
            events = merge_new(events, inbox)
            events = merge_new(events, self.pr_events(events, nows))
            cursor = {**cursor, "comments_since": newest or cursor.get("comments_since"), "last_run": nows}
            try:
                self.store.write(events, cursor, now, f"Ingest {len(events) - len(journal)} event(s)")
            except PushRejected:
                continue  # someone else advanced the journal: rebuild on top of it
            replied = self._reply(events, cursor, now)
            return {"appended": len(events) - len(journal), "replied": replied, "attempts": attempt + 1}
        raise RuntimeError("could not publish the journal after several attempts")

    def _reply(self, events: list[dict], cursor: dict, now) -> int:
        """Post one reply per decision. Best effort: a crash here can only cause a duplicate reply."""
        state = fold(events, until=now)
        start = cursor.get("replied", 0)
        pending = [d for d in state.decisions[start:] if d.get("issue")]
        for d in pending:
            mark = "✅" if d["accepted"] else "❌"
            self.gh.comment(d["issue"], f"{mark} `{d['kind']}` {d.get('task') or ''} by @{d['actor']}: {d['message']}\n\n<!-- fm:{d['event']} -->")
        if pending or start != len(state.decisions):
            for _ in range(MAX_ATTEMPTS):
                try:
                    self.store.sync()
                    c = {**self.store.cursor(), "replied": max(len(state.decisions), self.store.cursor().get("replied", 0))}
                    self.store.write(self.store.events(), c, now, "Record replies")
                    break
                except PushRejected:
                    continue
        return len(pending)


def labels_for(status: str) -> str:
    assert status in STATES
    return "fm:" + status.lower().replace("_", "-")
