"""Read-only proposal of candidate tasks from issues a project consented to; never adds a task."""

from .pilot import PilotError
from .pilot_github import GitHubReader

# 3 repository reads + 15 issues x (1 issue + up to 2 timeline pages) = 48, under GitHub's 60 unauthenticated reads per hour.
MAX_SCAN = 15
TIMELINE_PAGES = 2


def _title(issue, number):
    title = issue.get("title") if isinstance(issue.get("title"), str) else ""
    title = title.replace("\0", "").strip().encode("utf-8")[:256].decode("utf-8", "ignore").strip()
    return title or f"Issue {number}"


def _human_work(reader, path, number):
    """Reason to leave the issue to the humans already on it, or None."""
    linked, events = 0, []
    for page in range(1, TIMELINE_PAGES + 1):
        batch = reader._request(f"{path}/issues/{number}/timeline?per_page=100&page={page}")
        if not isinstance(batch, list) or len(batch) > 100:
            raise PilotError("github_unavailable")
        events += batch
        if len(batch) < 100:
            break
    else:
        return "timeline_too_long"
    for event in events:
        kind = event.get("event") if isinstance(event, dict) else None
        linked += {"connected": 1, "disconnected": -1}.get(kind, 0)
        source = event.get("source") if kind == "cross-referenced" else None
        other = source.get("issue") if isinstance(source, dict) else None
        if isinstance(other, dict) and "pull_request" in other and other.get("state") == "open":
            return "open_pull_request"
    return "linked_pull_request" if linked > 0 else None


def propose(ledger, token=None, *, opener=None):
    repository, known = ledger.task_issues()
    reader = GitHubReader(token, opener=opener)
    path, head = reader.repository(repository)
    consent = reader.consent(path, head)
    candidates, skipped = [], {}
    for number in consent["issues"][:MAX_SCAN]:
        if number in known:
            skipped[str(number)] = "already_a_task"
            continue
        issue = reader._request(f"{path}/issues/{number}", missing=True)
        if not isinstance(issue, dict) or issue.get("number") != number:
            reason = "unavailable"
        elif "pull_request" in issue:
            reason = "pull_request"
        elif issue.get("state") != "open":
            reason = "closed"
        elif issue.get("locked"):
            reason = "locked"
        elif issue.get("assignees") or issue.get("assignee"):
            reason = "assigned"
        else:
            reason = _human_work(reader, path, number)
        if reason:
            skipped[str(number)] = reason
            continue
        title = _title(issue, number)
        labels = issue.get("labels") if isinstance(issue.get("labels"), list) else []
        candidates.append({
            "issue": number, "title": title,
            "labels": [label["name"] for label in labels if isinstance(label, dict) and isinstance(label.get("name"), str)],
            "comments": issue["comments"] if type(issue.get("comments")) is int else None,
            "updated_at": issue["updated_at"] if isinstance(issue.get("updated_at"), str) else None,
            # Ready to pipe into `add-task` once the maintainer picks it and narrows the paths if needed.
            "add_task": {"task": f"issue-{number}", "issue": number, "base": head, "title": title,
                         "paths": consent["read"]},
        })
    return {"repository": repository, "base": head, "candidates": candidates, "skipped": skipped,
            "truncated": len(consent["issues"]) > MAX_SCAN}
