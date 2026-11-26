import base64
import io
import json
import sys
from urllib.error import HTTPError

import pytest

from forgemesh.pilot import Pilot, PilotError


HEAD = "c" * 40
REPO = "/repos/example/project"


def issue(number, **extra):
    return {"number": number, "state": "open", "locked": False, "assignees": [], "title": f"Issue {number}",
            "labels": [{"name": "docs"}], "comments": 2, "updated_at": "2026-11-20T10:00:00Z"} | extra


def pr_reference(state):
    return {"event": "cross-referenced", "source": {"type": "issue", "issue": {"number": 99, "state": state,
                                                                                   "pull_request": {}}}}


class API:
    def __init__(self, consent, issues, timelines=None):
        self.consent, self.issues, self.timelines = consent, issues, timelines or {}
        self.requests = []

    def open(self, request, *, timeout):
        assert request.get_method() == "GET" and timeout <= 10
        path = request.full_url.removeprefix("https://api.github.com")
        self.requests.append((path, request.get_header("Authorization")))
        if path == REPO:
            payload = {"full_name": "example/project", "private": False, "default_branch": "main"}
        elif path == REPO + "/commits/main":
            payload = {"sha": HEAD}
        elif path == f"{REPO}/contents/.github/nexus.json?ref={HEAD}":
            if self.consent is None:
                raise HTTPError(request.full_url, 404, "Not Found", {}, io.BytesIO(b"{}"))
            raw = json.dumps(self.consent).encode()
            payload = {"type": "file", "encoding": "base64", "content": base64.encodebytes(raw).decode()}
        elif path.startswith(REPO + "/issues/") and "/timeline" in path:
            number = int(path.split("/")[5])
            page = int(path.rsplit("page=", 1)[1])
            events = self.timelines.get(number, [])
            payload = events[(page - 1) * 100:page * 100]
        elif path.startswith(REPO + "/issues/"):
            number = int(path.rsplit("/", 1)[1])
            if number not in self.issues:
                raise HTTPError(request.full_url, 404, "Not Found", {}, io.BytesIO(b"{}"))
            payload = self.issues[number]
        else:
            raise AssertionError(path)
        return io.BytesIO(json.dumps(payload).encode())


@pytest.fixture
def ledger(tmp_path):
    ledger = Pilot(tmp_path / "pilot.db")
    ledger.initialize("example/project")
    return ledger


def propose(ledger, api, token=None):
    from forgemesh.pilot_discovery import propose

    return propose(ledger, token, opener=api.open)


def test_proposes_only_consented_unclaimed_issues_and_never_adds_tasks(ledger):
    ledger.add_task("known", 8, "b" * 40, "Already selected")
    api = API({"nexus": 1, "issues": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10], "read": ["docs/", "README.md"]}, {
        1: issue(1),
        2: issue(2, assignees=[{"login": "human"}]),
        3: issue(3),
        4: issue(4, state="closed"),
        5: issue(5, locked=True),
        6: issue(6, pull_request={}),
        7: issue(7),
        9: issue(9),
        10: issue(10),
    }, {
        3: [pr_reference("open")],
        7: [pr_reference("closed"), {"event": "commented"}],
        9: [{"event": "connected"}],
        10: [{"event": "connected"}, {"event": "disconnected"}],
    })
    result = propose(ledger, api)
    assert result["base"] == HEAD
    assert [c["issue"] for c in result["candidates"]] == [1, 7, 10]
    assert result["candidates"][0] == {
        "issue": 1, "title": "Issue 1", "labels": ["docs"], "comments": 2, "updated_at": "2026-11-20T10:00:00Z",
        "add_task": {"task": "issue-1", "issue": 1, "base": HEAD, "title": "Issue 1", "paths": ["docs/", "README.md"]},
    }
    assert result["skipped"] == {"2": "assigned", "3": "open_pull_request", "4": "closed", "5": "locked",
                                 "6": "pull_request", "8": "already_a_task", "9": "linked_pull_request"}
    assert [event["event"] for event in ledger.audit()] == ["initialized", "task_added"]
    assert all(auth is None for _, auth in api.requests)


def test_without_consent_there_is_nothing_to_propose(ledger):
    with pytest.raises(PilotError, match="no_consent"):
        propose(ledger, API(None, {1: issue(1)}))
    with pytest.raises(PilotError, match="invalid_consent"):
        propose(ledger, API({"nexus": 1, "issues": [1], "read": ["../x"]}, {1: issue(1)}))


def test_missing_issue_and_unbounded_timeline_are_skipped_not_guessed(ledger):
    api = API({"nexus": 1, "issues": [1, 2], "read": []}, {1: issue(1)},
              {1: [{"event": "commented"}] * 300})
    result = propose(ledger, api)
    assert result["candidates"] == []
    assert result["skipped"] == {"1": "timeline_too_long", "2": "unavailable"}


def test_scan_is_bounded_and_long_titles_fit_the_task_limit(ledger):
    issues = {n: issue(n, title="x" * 400) for n in range(1, 41)}
    api = API({"nexus": 1, "issues": list(issues), "read": []}, issues)
    result = propose(ledger, api)
    assert [c["issue"] for c in result["candidates"]] == list(range(1, 16))
    assert result["truncated"] is True
    assert len(result["candidates"][0]["add_task"]["title"]) == 256
    # Stays under GitHub's 60 unauthenticated reads per hour.
    assert len(api.requests) == 3 + 15 * 2


def test_operator_cli_uses_optional_env_token_and_never_echoes_it(ledger, tmp_path, monkeypatch, capsys):
    from forgemesh import pilot_cli, pilot_github

    api = API({"nexus": 1, "issues": [1], "read": []}, {1: issue(1)})
    monkeypatch.setattr(pilot_github, "build_opener", lambda *handlers: type("O", (), {"open": api.open})())
    secret = "ghs_" + "z" * 36
    monkeypatch.setenv("NEXUS_GITHUB_TOKEN", secret)
    monkeypatch.setattr(sys, "argv", ["nexus-pilot", str(tmp_path / "pilot.db"), "propose"])
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(b"{}")))
    assert pilot_cli.main() == 0
    out = capsys.readouterr().out
    assert secret not in out
    assert [c["issue"] for c in json.loads(out)["candidates"]] == [1]
    assert all(auth == "Bearer " + secret for _, auth in api.requests)
