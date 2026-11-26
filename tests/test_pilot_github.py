import base64
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
CONSENT = {"nexus": 1, "issues": [7], "read": ["docs/", "README.md"]}


@pytest.fixture
def approved(tmp_path):
    path = tmp_path / "pilot.db"
    ledger = Pilot(path)
    ledger.initialize("example/project")
    author = ledger.enroll("author", "alice", "contributor")
    reviewer = ledger.enroll("reviewer", "bob", "reviewer")
    approver = ledger.enroll("approver", "carol", "maintainer")
    publisher = ledger.enroll("publisher", "worker", "publisher")
    ledger.add_task("guide", 7, BASE, "Check the guide", ["docs/guide.md", "README.md"])
    digest = ledger.submit(author, "guide", ledger.claim(author, "guide"), REPORT)
    ledger.review(reviewer, "guide", digest, "pass", "Checked the pinned version")
    marker = ledger.authorize(approver, "guide", digest)
    return path, ledger, publisher, approver, marker


class API:
    def __init__(self, *, base=BASE, lose_response=False, issue=None, consent=CONSENT,
                 compare=None):
        self.base = base
        self.compare = {"status": "ahead", "total_commits": 1, "files": [{"filename": "docs/guide.md"}]} \
            if compare is None else compare
        self.consent = consent
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
        elif path == f"/repos/example/project/compare/{BASE}...{self.base}":
            payload = self.compare
        elif path == f"/repos/example/project/contents/.github/nexus.json?ref={self.base}":
            if self.consent is None:
                raise HTTPError(request.full_url, 404, "Not Found", {}, io.BytesIO(b"{}"))
            raw = self.consent if isinstance(self.consent, bytes) else json.dumps(self.consent).encode()
            payload = {"type": "file", "encoding": "base64", "content": base64.encodebytes(raw).decode()}
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


def test_operator_cli_publishes_with_env_token_once_and_never_echoes_it(approved, monkeypatch, capsys):
    import sys

    from forgemesh import pilot_cli, pilot_github

    path, _, token, _, _ = approved
    api = API()
    secret = "ghs_" + "y" * 36
    monkeypatch.setattr(pilot_github, "build_opener", lambda *handlers: type("O", (), {"open": api.open})())

    def run(env=secret, **payload):
        if env is None:
            monkeypatch.delenv("NEXUS_GITHUB_TOKEN", raising=False)
        else:
            monkeypatch.setenv("NEXUS_GITHUB_TOKEN", env)
        monkeypatch.setattr(sys, "argv", ["nexus-pilot", str(path), "publish-github"])
        monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(json.dumps(payload).encode())))
        code = pilot_cli.main()
        out = capsys.readouterr().out
        assert secret not in out
        return code, json.loads(out)

    request = {"token": token, "task": "guide", "bot_user_id": 42}
    assert run(None, **request) == (1, {"error": "invalid_publisher_configuration"})
    assert run(**request, extra=1) == (1, {"error": "invalid_input"})
    assert run(**request) == (0, 123)
    assert run(**request) == (0, 123)
    assert [path for method, path in api.requests if method == "POST"] == [COMMENTS]


@pytest.mark.parametrize("consent,error", [
    (None, "no_consent"),
    ({"nexus": 1, "issues": [], "read": ["docs/", "README.md"]}, "no_consent"),
    ({"nexus": 1, "issues": [7], "read": ["docs/"]}, "no_consent"),
    ({"nexus": 1, "issues": [7], "read": ["doc"]}, "no_consent"),
    ({"nexus": 2, "issues": [7], "read": ["docs/"]}, "invalid_consent"),
    ({"nexus": 1, "issues": [7], "read": ["../docs/"]}, "invalid_consent"),
    ({"nexus": 1, "issues": [7, 7], "read": ["docs/"]}, "invalid_consent"),
    ({"nexus": 1, "issues": [7], "read": ["docs/"], "extra": 1}, "invalid_consent"),
    (b"not json", "invalid_consent"),
])
def test_github_publishes_only_with_current_maintainer_consent(approved, consent, error):
    _, ledger, token, _, _ = approved
    api = API(consent=consent)
    with pytest.raises(PilotError, match=error):
        gateway(api).publish(ledger, token, "guide")
    assert all(method == "GET" for method, _ in api.requests)
    assert "dispatch_started" not in [event["event"] for event in ledger.audit()]
    # Restoring consent in the repository lets the same authorization proceed once.
    api.consent = CONSENT
    assert gateway(api).publish(ledger, token, "guide") == 123


@pytest.mark.parametrize("compare,result", [
    ({"status": "ahead", "total_commits": 2, "files": [{"filename": "src/x.c"}, {"filename": ".github/nexus.json"}]}, 123),
    ({"status": "ahead", "total_commits": 1, "files": [{"filename": "docs/new.md"}]}, 123),
    ({"status": "ahead", "total_commits": 1, "files": [{"filename": "docs/guide.md"}]}, "stale_base"),
    ({"status": "ahead", "total_commits": 1, "files": [{"filename": "x", "previous_filename": "README.md"}]}, "stale_base"),
    ({"status": "diverged", "total_commits": 1, "files": [{"filename": "src/x.c"}]}, "stale_base"),
    ({"status": "ahead", "total_commits": 1, "files": [{"filename": f"f{n}"} for n in range(300)]}, "stale_base"),
    ({"status": "ahead", "total_commits": 250, "files": [{"filename": "src/x.c"}]}, "stale_base"),
    ({"status": "ahead", "total_commits": 1}, "stale_base"),
])
def test_moved_head_is_stale_only_when_files_in_scope_changed(approved, compare, result):
    _, ledger, token, _, _ = approved
    api = API(base="c" * 40, compare=compare)
    if result == 123:
        assert gateway(api).publish(ledger, token, "guide") == 123
        started = [event for event in ledger.audit() if event["event"] == "dispatch_started"]
        assert started[0]["details"]["head"] == "c" * 40
    else:
        with pytest.raises(PilotError, match=result):
            gateway(api).publish(ledger, token, "guide")
        assert all(method == "GET" for method, _ in api.requests)


def test_adding_only_the_consent_file_keeps_an_unscoped_report_current(tmp_path):
    ledger = Pilot(tmp_path / "pilot.db")
    ledger.initialize("example/project")
    author = ledger.enroll("author", "alice", "contributor")
    reviewer = ledger.enroll("reviewer", "bob", "reviewer")
    approver = ledger.enroll("approver", "carol", "maintainer")
    publisher = ledger.enroll("publisher", "worker", "publisher")
    ledger.add_task("guide", 7, BASE, "Check the guide")
    digest = ledger.submit(author, "guide", ledger.claim(author, "guide"), REPORT)
    ledger.review(reviewer, "guide", digest, "pass", "Checked")
    ledger.authorize(approver, "guide", digest)
    other = {"status": "ahead", "total_commits": 2, "files": [{"filename": ".github/nexus.json"}, {"filename": "x"}]}
    with pytest.raises(PilotError, match="stale_base"):
        gateway(API(base="c" * 40, compare=other)).publish(ledger, publisher, "guide")
    only = {"status": "ahead", "total_commits": 1, "files": [{"filename": ".github/nexus.json"}]}
    assert gateway(API(base="c" * 40, compare=only)).publish(ledger, publisher, "guide") == 123
