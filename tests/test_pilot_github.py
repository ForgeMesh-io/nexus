import io
import json
from urllib.error import HTTPError, URLError

import pytest

from forgemesh.pilot import Pilot, PilotError


BASE = "b" * 40
REPORT = "The example omits a step.\n@team do not notify"
ISSUE = "/repos/example/project/issues/7"
HEAD = "/repos/example/project/commits/main"
COMMENTS = ISSUE + "/comments"


@pytest.fixture
def approved(tmp_path):
    path = tmp_path / "pilot.db"
    ledger = Pilot(path)
    ledger.initialize("example/project")
    author = ledger.enroll("author", "alice", "contributor")
    reviewer = ledger.enroll("reviewer", "bob", "reviewer")
    approver = ledger.enroll("approver", "carol", "maintainer")
    publisher = ledger.enroll("publisher", "worker", "publisher")
    ledger.add_task("guide", 7, BASE, "Check the guide")
    digest = ledger.submit(author, "guide", ledger.claim(author, "guide"), REPORT)
    ledger.review(reviewer, "guide", digest, "pass", "Checked the pinned version")
    marker = ledger.authorize(approver, "guide", digest)
    return path, ledger, publisher, approver, marker


class API:
    def __init__(self, *, base=BASE, lose_response=False, issue=None):
        self.base = base
        self.issue = {"number": 7, "state": "open"} if issue is None else issue
        self.lose_response = lose_response
        self.comments = []
        self.requests = []

    def open(self, request, *, timeout):
        path = request.full_url.removeprefix("https://api.github.com")
        method = request.get_method()
        self.requests.append((method, path))
        assert path.startswith("/repos/example/project")
        assert timeout <= 10
        if method == "POST":
            assert path == COMMENTS
            body = json.loads(request.data)["body"]
            self.comments.append({"id": 123, "user": {"id": 42}, "body": body})
            if self.lose_response:
                raise URLError("response lost after acceptance")
            payload = self.comments[-1]
        elif path == "/repos/example/project":
            payload = {"full_name": "example/project", "private": False, "default_branch": "main"}
        elif path == ISSUE:
            payload = self.issue
        elif path == HEAD:
            payload = {"sha": self.base}
        else:
            assert path == COMMENTS + "?per_page=100&page=1"
            payload = self.comments
        return io.BytesIO(json.dumps(payload).encode())


def gateway(api):
    from forgemesh.pilot_github import GitHubPublisher

    return GitHubPublisher("ghs_" + "x" * 36, 42, opener=api.open)


def test_github_gateway_only_posts_to_authorized_issue_once(approved):
    _, ledger, token, _, marker = approved
    api = API()
    publisher = gateway(api)
    assert publisher.publish(ledger, token, "guide") == 123
    assert publisher.publish(ledger, token, "guide") == 123
    assert [path for method, path in api.requests if method == "POST"] == [COMMENTS]
    assert api.comments[0]["body"].startswith(f"<!-- forgemesh-nexus:{marker} -->\n\n")
    assert "\n    @team do not notify" in api.comments[0]["body"]


def test_github_lost_mutation_response_reconciles_after_restart_without_send(approved):
    path, ledger, token, approver, _ = approved
    api = API(lose_response=True)
    with pytest.raises(PilotError, match="uncertain_dispatch"):
        gateway(api).publish(ledger, token, "guide")
    ledger.stop(approver)
    assert gateway(api).publish(Pilot(path), token, "guide") == 123
    assert [path for method, path in api.requests if method == "POST"] == [COMMENTS]


def test_restored_snapshot_of_ambiguous_dispatch_never_sends_again(approved, tmp_path):
    import sqlite3
    from contextlib import closing

    path, ledger, token, _, _ = approved
    api = API(lose_response=True)
    with pytest.raises(PilotError, match="uncertain_dispatch"):
        gateway(api).publish(ledger, token, "guide")
    restored = tmp_path / "restored" / "pilot.db"
    restored.parent.mkdir()
    with closing(sqlite3.connect(path)) as source, closing(sqlite3.connect(restored)) as target:
        source.backup(target)
    api.comments.clear()
    for _ in range(2):
        with pytest.raises(PilotError, match="uncertain_dispatch"):
            gateway(api).publish(Pilot(restored), token, "guide")
    assert [path for method, path in api.requests if method == "POST"] == [COMMENTS]
    assert [event["event"] for event in Pilot(restored).audit()][-1] == "dispatch_started"


def test_github_never_retries_after_missing_or_wrong_author_receipt(approved):
    path, ledger, token, _, _ = approved
    api = API(lose_response=True)
    with pytest.raises(PilotError, match="uncertain_dispatch"):
        gateway(api).publish(ledger, token, "guide")
    api.comments[0]["user"]["id"] = 99
    for _ in range(2):
        with pytest.raises(PilotError, match="uncertain_dispatch"):
            gateway(api).publish(Pilot(path), token, "guide")
    assert len(api.comments) == 1


@pytest.mark.parametrize("base,issue,error", [
    ("a" * 40, None, "stale_base"),
    (BASE, {"number": 7, "state": "closed"}, "ineligible_issue"),
    (BASE, {"number": 7, "state": "open", "pull_request": {}}, "ineligible_issue"),
])
def test_github_stale_or_ineligible_target_never_dispatches(approved, base, issue, error):
    _, ledger, token, _, _ = approved
    api = API(base=base, issue=issue)
    with pytest.raises(PilotError, match=error):
        gateway(api).publish(ledger, token, "guide")
    assert all(method == "GET" for method, _ in api.requests)
    assert "dispatch_started" not in [event["event"] for event in ledger.audit()]


def test_github_429_does_not_repeat_the_post(approved):
    _, ledger, token, _, _ = approved

    class RateLimited(API):
        def open(self, request, *, timeout):
            if request.get_method() == "POST":
                self.requests.append(("POST", COMMENTS))
                raise HTTPError(request.full_url, 429, "limited", {}, io.BytesIO())
            return super().open(request, timeout=timeout)

    api = RateLimited()
    for _ in range(2):
        with pytest.raises(PilotError, match="uncertain_dispatch"):
            gateway(api).publish(ledger, token, "guide")
    assert [path for method, path in api.requests if method == "POST"] == [COMMENTS]
