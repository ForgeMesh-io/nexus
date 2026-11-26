"""Publisher for already approved text reports, separate from the participant API."""

import base64
import binascii
import http.client
import json
import re
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from .pilot import PilotError, valid_paths

CONSENT_FILE = ".github/nexus.json"


def _covers(scope, path):
    return scope == path or (scope.endswith("/") and path.startswith(scope))


def parse_consent(raw):
    try:
        consent = json.loads(raw)
    except (ValueError, RecursionError):
        raise PilotError("invalid_consent") from None
    # `read` has the same limit as a task's paths, so a proposal can always reuse it unchanged.
    if (not isinstance(consent, dict) or set(consent) != {"nexus", "issues", "read"} or consent["nexus"] != 1
            or type(consent["nexus"]) is not int or not isinstance(consent["issues"], list)
            or len(consent["issues"]) > 100 or len(set(consent["issues"])) != len(consent["issues"])
            or not all(type(n) is int and 1 <= n <= 2**31 - 1 for n in consent["issues"])
            or not valid_paths(consent["read"], 16)):
        raise PilotError("invalid_consent")
    return consent


def check_consent(consent, issue, paths):
    """The maintainer-owned file must name this issue and cover every path the task reads."""
    if issue not in consent["issues"] or not all(
            any(_covers(scope, path) for scope in consent["read"]) for path in paths):
        raise PilotError("no_consent")


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


TOKEN = r"ghs_[a-zA-Z0-9_.=-]{36,2048}"


class GitHubReader:
    """Public-repository reads; without a token GitHub allows 60 requests per hour per IP."""

    def __init__(self, token=None, *, opener=None):
        if token is not None and (not isinstance(token, str) or not re.fullmatch(TOKEN, token)):
            raise PilotError("invalid_github_token")
        self._token = token
        self._open = opener or build_opener(ProxyHandler({}), _NoRedirect()).open

    def _request(self, path, *, body=None, missing=False):
        data = None if body is None else json.dumps({"body": body}).encode("utf-8")
        headers = {
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "User-Agent": "ForgeMesh-Nexus-Pilot",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self._token:
            headers["Authorization"] = "Bearer " + self._token
        request = Request("https://api.github.com" + path, data=data, headers=headers)
        error = "github_unavailable" if body is None else "uncertain_dispatch"
        try:
            with self._open(request, timeout=10) as response:
                raw = response.read(2_097_153)
            if len(raw) > 2_097_152:
                raise ValueError("response too large")
            return json.loads(raw)
        except HTTPError as exc:
            if missing and exc.code == 404:
                return None
            raise PilotError(error) from None
        except (OSError, http.client.HTTPException, ValueError, RecursionError):
            raise PilotError(error) from None

    def repository(self, repository):
        """The public repository, its default-branch head and its current consent file."""
        path = f"/repos/{repository}"
        repo = self._request(path)
        if (not isinstance(repo, dict) or repo.get("private") is not False
                or str(repo.get("full_name", "")).lower() != repository
                or not isinstance(repo.get("default_branch"), str) or not repo["default_branch"]):
            raise PilotError("ineligible_repository")
        head = self._request(f'{path}/commits/{quote(repo["default_branch"], safe="")}')
        if not isinstance(head, dict) or not re.fullmatch(r"[0-9a-f]{40}", str(head.get("sha", ""))):
            raise PilotError("github_unavailable")
        return path, head["sha"]

    def consent(self, path, head):
        file = self._request(f"{path}/contents/{CONSENT_FILE}?ref={head}", missing=True)
        if file is None:
            raise PilotError("no_consent")
        if not isinstance(file, dict) or file.get("type") != "file" or file.get("encoding") != "base64":
            raise PilotError("invalid_consent")
        try:
            raw = base64.b64decode(str(file.get("content", "")).replace("\n", ""), validate=True)
        except (binascii.Error, ValueError):
            raise PilotError("invalid_consent") from None
        if len(raw) > 65_536:
            raise PilotError("invalid_consent")
        return parse_consent(raw)


class GitHubPublisher(GitHubReader):
    def __init__(self, installation_token, bot_user_id, *, opener=None):
        if (not isinstance(installation_token, str) or not re.fullmatch(TOKEN, installation_token)
                or type(bot_user_id) is not int or bot_user_id < 1):
            raise PilotError("invalid_publisher_configuration")
        super().__init__(installation_token, opener=opener)
        self._bot_user_id = bot_user_id

    @staticmethod
    def _body(intent):
        text = "\n".join("    " + line for line in intent["report"].splitlines())
        return (f'<!-- forgemesh-nexus:{intent["marker"]} -->\n\n'
                f'Nexus report for `{intent["base"]}`. Report SHA-256: `{intent["digest"]}`.\n\n{text}')

    def _receipt(self, comment, body):
        if (isinstance(comment, dict) and comment.get("body") == body
                and isinstance(comment.get("user"), dict) and comment["user"].get("id") == self._bot_user_id
                and type(comment.get("id")) is int and 1 <= comment["id"] <= 2**63 - 1):
            return comment["id"]

    def publish(self, ledger, token, task):
        intent = ledger.dispatched(token, task)
        if intent is not None:
            return self._reconcile(ledger, token, intent)
        target = ledger.pending_target(token, task)
        if target is None:
            raise PilotError("no_dispatch")
        issue = target["issue"]
        path, head = self.repository(target["repository"])
        path_issue = f"{path}/issues/{issue}"
        current = self._request(path_issue)
        if (not isinstance(current, dict) or current.get("number") != issue
                or current.get("state") != "open" or current.get("locked") or "pull_request" in current):
            raise PilotError("ineligible_issue")
        check_consent(self.consent(path, head), issue, target["paths"])
        base = target["base"] if head == target["base"] or self._unchanged(path, target, head) else head
        intent = ledger.begin_dispatch(token, task, base, head)
        if intent is None:
            raise PilotError("no_dispatch")
        body = self._body(intent)
        receipt = self._receipt(self._request(f"{path_issue}/comments", body=body), body)
        if receipt is None:
            raise PilotError("uncertain_dispatch")
        return ledger.record_publication(token, intent["marker"], receipt)

    def _unchanged(self, path, target, head):
        """A moved branch keeps the report current only if no file the task reads changed."""
        diff = self._request(f'{path}/compare/{target["base"]}...{head}')
        # GitHub truncates compare results (300 files, 250 commits); treat a possibly partial list as changed.
        if (not isinstance(diff, dict) or diff.get("status") != "ahead" or not isinstance(diff.get("files"), list)
                or len(diff["files"]) >= 300 or type(diff.get("total_commits")) is not int
                or not 1 <= diff["total_commits"] < 250):
            return False
        # The consent file is re-read at `head`; a task without paths tolerates no other change.
        scopes = target["paths"] or [""]
        for changed in diff["files"]:
            names = [changed.get(key) for key in ("filename", "previous_filename")] if isinstance(changed, dict) else [None]
            if not isinstance(names[0], str) or any(
                    isinstance(name, str) and name != CONSENT_FILE
                    and any(scope == "" or _covers(scope, name) for scope in scopes) for name in names):
                return False
        return True

    def _reconcile(self, ledger, token, intent):
        path = f'/repos/{intent["repository"]}/issues/{intent["issue"]}/comments'
        body = self._body(intent)
        # shortcut: bounded scan of up to 500 comments; use an authenticated receipt lookup on busier issues.
        matches = []
        for page in range(1, 6):
            comments = self._request(f"{path}?per_page=100&page={page}")
            if not isinstance(comments, list) or len(comments) > 100:
                raise PilotError("uncertain_dispatch")
            matches.extend(receipt for comment in comments if (receipt := self._receipt(comment, body)))
            if len(comments) < 100:
                break
        else:
            raise PilotError("uncertain_dispatch")
        if len(matches) != 1:
            raise PilotError("uncertain_dispatch")
        return ledger.record_publication(token, intent["marker"], matches[0])
