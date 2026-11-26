"""Read-only proposal of candidate tasks from issues a project consented to; never adds a task."""

from .pilot_github import GitHubReader

# 3 repository reads + 15 issues x (1 issue + up to 2 timeline pages) = 48, under GitHub's 60 unauthenticated reads per hour.
MAX_SCAN = 15


def _title(issue, number):
    title = issue.get("title") if isinstance(issue.get("title"), str) else ""
    title = title.replace("\0", "").strip().encode("utf-8")[:256].decode("utf-8", "ignore").strip()
    return title or f"Issue {number}"


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
            reason = reader.human_work(f"{path}/issues/{number}")
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
