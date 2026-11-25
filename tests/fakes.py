"""In-memory stand-ins for GitHub used by the tests."""

from __future__ import annotations

import itertools
import threading

_ids = itertools.count(1000)


class FakeGitHub:
    def __init__(self):
        self.lock = threading.Lock()
        self.comments: list[dict] = []
        self.replies: list[tuple[int, str]] = []
        self.prs: dict[int, dict] = {}
        self.diffs: dict[int, str] = {}
        self.files: dict[int, list[str]] = {}

    def post(self, user: str, issue: int, body: str, created_at: str) -> dict:
        with self.lock:
            c = {"id": next(_ids), "user": {"login": user, "type": "User"}, "body": body, "created_at": created_at,
                 "issue_url": f"https://api.github.com/repos/o/r/issues/{issue}", "html_url": f"https://github.com/o/r/issues/{issue}"}
            self.comments.append(c)
            return c

    def open_pr(self, number: int, author: str, sha: str, diff: str = "diff --git a/x b/x\n+x\n", files=("src/x.py",)):
        self.prs[number] = {"number": number, "state": "open", "merged": False, "user": {"login": author}, "head": {"sha": sha}}
        self.diffs[number] = diff
        self.files[number] = list(files)

    # -- API used by the coordinator --
    def issue_comments_since(self, since):
        with self.lock:
            snapshot = list(self.comments)
        return [c for c in snapshot if since is None or c["created_at"] >= since]

    def comment(self, issue, body):
        with self.lock:
            self.replies.append((issue, body))

    def pull(self, n):
        if n not in self.prs:
            raise KeyError(n)
        return self.prs[n]

    def pull_files(self, n):
        return [{"filename": f} for f in self.files[n]]

    def pull_diff(self, n):
        return self.diffs[n]
