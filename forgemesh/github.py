"""Minimal GitHub REST client (standard library only).

Uses GITHUB_TOKEN from the environment. Handles pagination, rate limits
(primary and secondary) with bounded back-off, and never logs the token.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request

API = os.environ.get("GITHUB_API_URL", "https://api.github.com")


class GitHubError(Exception):
    pass


class GitHub:
    def __init__(self, repo: str, token: str | None = None, max_wait: int = 300):
        self.repo = repo
        self.token = token or os.environ.get("GITHUB_TOKEN", "")
        self.max_wait = max_wait

    def request(self, method: str, path: str, body=None, accept: str = "application/vnd.github+json"):
        url = path if path.startswith("http") else f"{API}{path}"
        data = json.dumps(body).encode() if body is not None else None
        for attempt in range(6):
            req = urllib.request.Request(url, data=data, method=method)
            req.add_header("Accept", accept)
            req.add_header("X-GitHub-Api-Version", "2022-11-28")
            req.add_header("User-Agent", "forgemesh-coordinator")
            if self.token:
                req.add_header("Authorization", f"Bearer {self.token}")
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    raw = r.read()
                    link = r.headers.get("Link", "")
                    return (json.loads(raw) if raw and "json" in r.headers.get("Content-Type", "") else raw.decode()), link
            except urllib.error.HTTPError as e:
                if e.code in (403, 429) and attempt < 5:
                    wait = int(e.headers.get("Retry-After") or 0)
                    if not wait and e.headers.get("X-RateLimit-Remaining") == "0":
                        wait = int(e.headers.get("X-RateLimit-Reset", "0")) - int(time.time())
                    wait = min(max(wait, 2 ** attempt * 5), self.max_wait)
                    time.sleep(wait)
                    continue
                if e.code >= 500 and attempt < 5:
                    time.sleep(2 ** attempt)
                    continue
                raise GitHubError(f"{method} {path}: HTTP {e.code} {e.read()[:300]!r}") from None
        raise GitHubError(f"{method} {path}: retries exhausted")

    def get(self, path: str, accept: str = "application/vnd.github+json"):
        return self.request("GET", path, accept=accept)[0]

    def paginate(self, path: str):
        url = f"{API}{path}{'&' if '?' in path else '?'}per_page=100"
        while url:
            page, link = self.request("GET", url)
            yield from page
            m = re.search(r'<([^>]+)>;\s*rel="next"', link or "")
            url = m.group(1) if m else None

    # -- helpers used by the coordinator -------------------------------
    def issue_comments_since(self, since: str | None):
        q = "/repos/{}/issues/comments?sort=created&direction=asc".format(self.repo)
        if since:
            q += f"&since={since}"
        return self.paginate(q)

    def comment(self, issue: int, body: str):
        return self.request("POST", f"/repos/{self.repo}/issues/{issue}/comments", {"body": body})[0]

    def pull(self, number: int):
        return self.get(f"/repos/{self.repo}/pulls/{number}")

    def pull_files(self, number: int):
        return list(self.paginate(f"/repos/{self.repo}/pulls/{number}/files"))

    def pull_diff(self, number: int) -> str:
        return self.get(f"/repos/{self.repo}/pulls/{number}", accept="application/vnd.github.diff")

    def pulls(self, state: str = "all"):
        return self.paginate(f"/repos/{self.repo}/pulls?state={state}&sort=updated&direction=desc")
