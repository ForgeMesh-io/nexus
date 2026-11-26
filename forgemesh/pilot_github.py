"""Publisher for already approved text reports, separate from the participant API."""

import http.client
import json
import re
from urllib.parse import quote
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from .pilot import PilotError


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class GitHubPublisher:
    def __init__(self, installation_token, bot_user_id, *, opener=None):
        if (not isinstance(installation_token, str)
                or not re.fullmatch(r"ghs_[a-zA-Z0-9_.=-]{36,2048}", installation_token)
                or type(bot_user_id) is not int or bot_user_id < 1):
            raise PilotError("invalid_publisher_configuration")
        self._token = installation_token
        self._bot_user_id = bot_user_id
        self._open = opener or build_opener(ProxyHandler({}), _NoRedirect()).open

    def _request(self, path, *, body=None):
        data = None if body is None else json.dumps({"body": body}).encode("utf-8")
        request = Request("https://api.github.com" + path, data=data, headers={
            "Authorization": "Bearer " + self._token,
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "User-Agent": "ForgeMesh-Nexus-Pilot",
            "X-GitHub-Api-Version": "2022-11-28",
        })
        error = "github_unavailable" if body is None else "uncertain_dispatch"
        try:
            with self._open(request, timeout=10) as response:
                raw = response.read(2_097_153)
            if len(raw) > 2_097_152:
                raise ValueError("response too large")
            return json.loads(raw)
        except (OSError, http.client.HTTPException, ValueError, RecursionError):
            raise PilotError(error) from None

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
        repository, issue = target
        path = f"/repos/{repository}"
        repo = self._request(path)
        if (not isinstance(repo, dict) or repo.get("private") is not False
                or str(repo.get("full_name", "")).lower() != repository
                or not isinstance(repo.get("default_branch"), str) or not repo["default_branch"]):
            raise PilotError("ineligible_repository")
        path_issue = f"{path}/issues/{issue}"
        current = self._request(path_issue)
        if (not isinstance(current, dict) or current.get("number") != issue
                or current.get("state") != "open" or current.get("locked") or "pull_request" in current):
            raise PilotError("ineligible_issue")
        head = self._request(f'{path}/commits/{quote(repo["default_branch"], safe="")}')
        if not isinstance(head, dict) or not re.fullmatch(r"[0-9a-f]{40}", str(head.get("sha", ""))):
            raise PilotError("github_unavailable")
        intent = ledger.begin_dispatch(token, task, head["sha"])
        if intent is None:
            raise PilotError("no_dispatch")
        body = self._body(intent)
        receipt = self._receipt(self._request(f"{path_issue}/comments", body=body), body)
        if receipt is None:
            raise PilotError("uncertain_dispatch")
        return ledger.record_publication(token, intent["marker"], receipt)

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
