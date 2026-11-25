"""Deterministic task state machine.

The journal is an append-only list of facts: configuration snapshots (``policy``,
``task``) and requests (``claim``, ``submit``, ``vote``...). ``fold`` replays it and
returns the state plus one decision per request. It is a pure function: the same
journal always yields the same state and the same decisions, on any machine.
Each request is evaluated against the policy and task definitions in force at that
point of the journal, so later configuration changes never rewrite past decisions.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

SYSTEM = "@system"  # the trusted coordinator; '@' is not allowed in GitHub logins

AVAILABLE, CLAIMED, IN_PROGRESS = "AVAILABLE", "CLAIMED", "IN_PROGRESS"
SUBMITTED, VALIDATING, CHANGES_REQUESTED = "SUBMITTED", "VALIDATING", "CHANGES_REQUESTED"
READY_TO_MERGE, MERGED, REJECTED = "READY_TO_MERGE", "MERGED", "REJECTED"
BLOCKED, EXPIRED, CANCELLED = "BLOCKED", "EXPIRED", "CANCELLED"

STATES = (AVAILABLE, CLAIMED, IN_PROGRESS, SUBMITTED, VALIDATING, CHANGES_REQUESTED,
          READY_TO_MERGE, MERGED, REJECTED, BLOCKED, EXPIRED, CANCELLED)
CLAIMABLE = {AVAILABLE, EXPIRED}
LEASED = {CLAIMED, IN_PROGRESS, CHANGES_REQUESTED}
IN_REVIEW = {SUBMITTED, VALIDATING, READY_TO_MERGE}
ACTIVE = LEASED | IN_REVIEW
TERMINAL = {MERGED, REJECTED, CANCELLED}

RISKS = ("low", "medium", "high", "critical")
DEFAULT_POLICY = {
    "paused": False,
    "lease_hours": 24,
    "max_renewals": 6,
    "max_active_claims_per_user": 2,
    "wip_limit_per_component": 3,
    "required_passes": {"low": 1, "medium": 2, "high": 2, "critical": 3},
    "maintainer_approval_from": "high",
    "trusted_vote_from": "high",
    "auto_merge_max_risk": "low",
    "maintainers": [],
    "trusted_validators": [],
    "protected_paths": [],
}


class Rejected(Exception):
    pass


def parse_time(value: str) -> datetime:
    t = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if t.tzinfo is None:
        raise ValueError(f"timestamp without timezone: {value}")
    return t.astimezone(timezone.utc)


def fmt_time(t: datetime) -> str:
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def risk_at_least(risk: str, threshold: str) -> bool:
    return threshold != "never" and RISKS.index(risk) >= RISKS.index(threshold)


def globs_overlap(a: str, b: str) -> bool:
    """Conservative overlap test between two path globs (may report false positives)."""
    if fnmatch.fnmatchcase(a, b) or fnmatch.fnmatchcase(b, a):
        return True
    pa = a.split("*")[0].split("?")[0].split("[")[0]
    pb = b.split("*")[0].split("?")[0].split("[")[0]
    wild_a, wild_b = pa != a, pb != b
    return (wild_a and pb.startswith(pa)) or (wild_b and pa.startswith(pb)) or (wild_a and wild_b and pa.startswith(pb))


@dataclass
class Task:
    definition: dict
    status: str = AVAILABLE
    claimant: str | None = None
    lease_expires: datetime | None = None
    renewals: int = 0
    submission: dict | None = None
    votes: dict = field(default_factory=dict)        # voter -> {"verdict", "sha", "evidence"}
    approval: dict | None = None                     # maintainer approval bound to a sha
    attempts: list = field(default_factory=list)     # {"actor", "from", "to", "outcome"}
    block_reason: str | None = None

    @property
    def id(self) -> str:
        return self.definition["id"]

    def to_json(self) -> dict:
        return {
            "id": self.id, "status": self.status, "claimant": self.claimant,
            "lease_expires": fmt_time(self.lease_expires) if self.lease_expires else None,
            "renewals": self.renewals, "submission": self.submission, "votes": self.votes,
            "approval": self.approval, "attempts": self.attempts, "block_reason": self.block_reason,
        }


@dataclass
class State:
    policy: dict = field(default_factory=lambda: dict(DEFAULT_POLICY))
    tasks: dict = field(default_factory=dict)        # id -> Task
    clock: datetime | None = None
    seen: set = field(default_factory=set)
    decisions: list = field(default_factory=list)    # {"event", "accepted", "message"}
    patch_index: dict = field(default_factory=dict)  # patch fingerprint -> task id

    # ---- derived views -------------------------------------------------
    def deps_satisfied(self, task: Task) -> bool:
        return all(d in self.tasks and self.tasks[d].status == MERGED
                   for d in task.definition.get("depends_on", []))

    def display_status(self, task: Task) -> str:
        if task.status in CLAIMABLE and not self.deps_satisfied(task):
            return BLOCKED
        return task.status

    def conflicts(self, task: Task) -> list[str]:
        """Active tasks touching the same files, excluding intentional parallel groups."""
        group = task.definition.get("parallel_group")
        out = []
        for other in self.tasks.values():
            if other.id == task.id or other.status not in ACTIVE:
                continue
            if group and other.definition.get("parallel_group") == group:
                continue
            if any(globs_overlap(a, b) for a in task.definition.get("files", [])
                   for b in other.definition.get("files", [])):
                out.append(other.id)
        return sorted(out)

    def component_load(self, component: str) -> int:
        return sum(1 for t in self.tasks.values()
                   if t.status in ACTIVE and component in t.definition.get("components", []))

    def active_claims(self, actor: str) -> int:
        return sum(1 for t in self.tasks.values() if t.claimant == actor and t.status in LEASED)

    def is_trusted_validator(self, actor: str) -> bool:
        return _is_maintainer(self, actor) or actor in self.policy.get("trusted_validators", [])

    def validation_needs(self, task: Task) -> dict:
        p, risk, sub = self.policy, task.definition["risk"], task.submission
        sha = sub["head_sha"]
        passes = [v for v, x in task.votes.items() if x["sha"] == sha and x["verdict"] == "pass"]
        maintainer_required = risk_at_least(risk, p["maintainer_approval_from"]) or bool(sub.get("violations"))
        return {
            "independent_passes": max(0, p["required_passes"][risk] - len(passes)),
            "trusted_pass": risk_at_least(risk, p["trusted_vote_from"]) and not any(self.is_trusted_validator(v) for v in passes),
            "maintainer_approval": maintainer_required and (task.approval or {}).get("sha") != sha,
        }

    def validation_queue(self) -> int:
        count = 0
        for task in self.tasks.values():
            if task.status in {SUBMITTED, VALIDATING}:
                needs = self.validation_needs(task)
                count += bool(needs["independent_passes"] or needs["trusted_pass"])
        return count

    def to_json(self) -> dict:
        return {
            "clock": fmt_time(self.clock) if self.clock else None,
            "paused": bool(self.policy.get("paused")),
            "tasks": {tid: {**t.to_json(), "display_status": self.display_status(t)}
                      for tid, t in sorted(self.tasks.items())},
        }


# ---- transitions ---------------------------------------------------------

def _expire(state: State) -> None:
    for t in state.tasks.values():
        if t.status in LEASED and t.lease_expires and t.lease_expires <= state.clock:
            _end_attempt(t, t.lease_expires, "expired")
            t.status, t.claimant, t.lease_expires, t.renewals = EXPIRED, None, None, 0


def _is_maintainer(state: State, actor: str) -> bool:
    return actor == SYSTEM or actor in state.policy.get("maintainers", [])


def _end_attempt(task: Task, now: datetime, outcome: str) -> None:
    if task.attempts and task.attempts[-1]["to"] is None:
        task.attempts[-1].update(to=fmt_time(now), outcome=outcome)


def _new_lease(state: State, task: Task) -> datetime:
    hours = task.definition.get("lease_hours", state.policy["lease_hours"])
    return state.clock + timedelta(hours=hours)


def _claim(state, task, ev):
    actor, p = ev["actor"], state.policy
    if p.get("paused"):
        raise Rejected("swarm is paused, no new claims")
    if task.status not in CLAIMABLE:
        raise Rejected(f"task is {task.status}" + (f" (claimed by @{task.claimant})" if task.claimant else ""))
    if not state.deps_satisfied(task):
        missing = [d for d in task.definition.get("depends_on", []) if d not in state.tasks or state.tasks[d].status != MERGED]
        raise Rejected("blocked by unfinished dependencies: " + ", ".join(missing))
    active = state.active_claims(actor)
    if active >= p["max_active_claims_per_user"]:
        raise Rejected(f"@{actor} already holds {active} active claims (limit {p['max_active_claims_per_user']})")
    for comp in task.definition.get("components", []):
        if state.component_load(comp) >= p["wip_limit_per_component"]:
            raise Rejected(f"work-in-progress limit reached for component '{comp}'")
    clash = state.conflicts(task)
    if clash:
        raise Rejected("overlaps files of active tasks: " + ", ".join(clash))
    task.status, task.claimant, task.renewals = CLAIMED, actor, 0
    task.lease_expires = _new_lease(state, task)
    task.votes, task.approval, task.submission = {}, None, None
    task.attempts.append({"actor": actor, "from": fmt_time(state.clock), "to": None, "outcome": None})
    return f"claimed by @{actor} until {fmt_time(task.lease_expires)}"


def _require_claimant(task, ev):
    if task.claimant != ev["actor"]:
        raise Rejected(f"only the claimant (@{task.claimant}) can do this" if task.claimant else "task is not claimed")


def _renew(state, task, ev):
    _require_claimant(task, ev)
    if task.status not in LEASED:
        raise Rejected(f"task is {task.status}, nothing to renew")
    if task.renewals >= state.policy["max_renewals"]:
        raise Rejected("maximum number of renewals reached; submit, release or ask a maintainer")
    task.renewals += 1
    task.lease_expires = _new_lease(state, task)
    if task.status == CLAIMED:
        task.status = IN_PROGRESS
    return f"lease renewed until {fmt_time(task.lease_expires)}"


def _start(state, task, ev):
    _require_claimant(task, ev)
    if task.status != CLAIMED:
        raise Rejected(f"task is {task.status}")
    task.status = IN_PROGRESS
    return "work started"


def _release(state, task, ev):
    if task.status not in LEASED | IN_REVIEW:
        raise Rejected(f"task is {task.status}, nothing to release")
    if ev["actor"] != task.claimant and not _is_maintainer(state, ev["actor"]):
        raise Rejected("only the claimant or a maintainer can release a task")
    _end_attempt(task, state.clock, "released")
    task.status, task.claimant, task.lease_expires, task.submission = AVAILABLE, None, None, None
    task.votes, task.approval = {}, None
    return "released, task is available again"


def _submit(state, task, ev):
    _require_claimant(task, ev)
    if task.status not in LEASED | {SUBMITTED, VALIDATING}:
        raise Rejected(f"task is {task.status}, cannot submit")
    sub = ev.get("submission") or {}
    if sub.get("error"):
        raise Rejected(sub["error"])
    for key in ("pr", "head_sha", "author"):
        if not sub.get(key):
            raise Rejected(f"submission is missing '{key}'")
    if sub["author"] != ev["actor"]:
        raise Rejected("the pull request must be authored by the claimant")
    if task.submission and task.submission["head_sha"] == sub["head_sha"]:
        raise Rejected("duplicate submission: this commit is already under validation")
    fp = sub.get("patch_id")
    if fp and state.patch_index.get(fp, task.id) != task.id:
        raise Rejected(f"identical patch already submitted for {state.patch_index[fp]}")
    if fp:
        state.patch_index[fp] = task.id
    task.submission = {k: sub[k] for k in ("pr", "head_sha", "author", "patch_id", "violations") if k in sub}
    task.submission["at"] = fmt_time(state.clock)
    task.votes, task.approval, task.lease_expires = {}, None, None
    task.status = SUBMITTED
    note = ""
    if sub.get("violations"):
        note = " — touches protected paths, maintainer review required: " + ", ".join(sub["violations"])
    return f"submission #{sub['pr']} @ {sub['head_sha'][:12]} recorded, waiting for independent validation{note}"


def _evaluate(state: State, task: Task) -> str:
    sha = task.submission["head_sha"]
    fails = [v for v, x in task.votes.items() if x["sha"] == sha and x["verdict"] == "fail"]
    threshold = state.policy["required_passes"][task.definition["risk"]]
    if any(state.is_trusted_validator(v) for v in fails) or len(fails) >= threshold:
        task.status = CHANGES_REQUESTED
        task.lease_expires = _new_lease(state, task)
        return "changes requested by validators: " + ", ".join("@" + v for v in sorted(fails))
    needs = state.validation_needs(task)
    ok = not any(needs.values())
    task.status = READY_TO_MERGE if ok else VALIDATING
    missing = []
    if needs["independent_passes"]:
        missing.append(f"{needs['independent_passes']} more independent pass vote(s)")
    if needs["trusted_pass"]:
        missing.append("a pass from a trusted validator")
    if needs["maintainer_approval"]:
        missing.append("maintainer approval")
    return "ready to merge" if ok else "still needs " + ", ".join(missing)


def _vote(state, task, ev):
    if task.status not in {SUBMITTED, VALIDATING, READY_TO_MERGE}:
        raise Rejected(f"task is {task.status}, nothing to validate")
    actor, sub = ev["actor"], task.submission
    if actor in (sub["author"], task.claimant):
        raise Rejected("authors cannot validate their own contribution")
    verdict, sha = ev.get("verdict"), (ev.get("sha") or "").lower()
    if verdict not in ("pass", "fail"):
        raise Rejected("verdict must be 'pass' or 'fail'")
    if len(sha) < 7 or not sub["head_sha"].startswith(sha):
        raise Rejected(f"vote must reference the submitted commit {sub['head_sha'][:12]}")
    if not ev.get("evidence"):
        raise Rejected("a vote must include evidence (link to logs or a results report)")
    task.votes[actor] = {"verdict": verdict, "sha": sub["head_sha"], "evidence": ev["evidence"], "at": fmt_time(state.clock)}
    return f"{verdict} vote from @{actor} recorded; " + _evaluate(state, task)


def _approve(state, task, ev):
    if not _is_maintainer(state, ev["actor"]):
        raise Rejected("only maintainers can approve")
    if task.status not in {SUBMITTED, VALIDATING}:
        raise Rejected(f"task is {task.status}, nothing to approve")
    sha = (ev.get("sha") or "").lower()
    if len(sha) < 7 or not task.submission["head_sha"].startswith(sha):
        raise Rejected(f"approval must reference the submitted commit {task.submission['head_sha'][:12]}")
    task.approval = {"by": ev["actor"], "sha": task.submission["head_sha"], "at": fmt_time(state.clock)}
    return "maintainer approval recorded; " + _evaluate(state, task)


def _merged(state, task, ev):
    if ev["actor"] != SYSTEM:
        raise Rejected("merge events can only come from the coordinator")
    if not task.submission or task.submission["pr"] != ev.get("pr"):
        raise Rejected("pull request is not the current submission")
    # A maintainer may merge manually; the merge is a fact, but bypassing validation is flagged.
    audit = []
    if task.status != READY_TO_MERGE:
        audit.append(f"merged while {task.status}")
    if ev.get("head_sha") != task.submission["head_sha"]:
        audit.append("merged commit differs from the submitted commit")
    _end_attempt(task, state.clock, "merged")
    task.status, task.lease_expires = MERGED, None
    task.submission["audit"] = audit
    return "merged" + (" — AUDIT: " + "; ".join(audit) if audit else "")


def _pr_closed(state, task, ev):
    if ev["actor"] != SYSTEM:
        raise Rejected("close events can only come from the coordinator")
    if task.status not in IN_REVIEW or not task.submission or task.submission["pr"] != ev.get("pr"):
        raise Rejected("pull request is not the current submission")
    task.status, task.submission, task.votes, task.approval = IN_PROGRESS, None, {}, None
    task.lease_expires = _new_lease(state, task)
    return "pull request closed without merge; task returned to its claimant"


def _pr_updated(state, task, ev):
    if ev["actor"] != SYSTEM:
        raise Rejected("update events can only come from the coordinator")
    if task.status not in IN_REVIEW or not task.submission or task.submission["pr"] != ev.get("pr"):
        raise Rejected("pull request is not the current submission")
    task.submission.update(head_sha=ev["head_sha"], patch_id=ev.get("patch_id"), violations=ev.get("violations", []))
    task.votes, task.approval, task.status = {}, None, SUBMITTED
    return f"new commit {ev['head_sha'][:12]} pushed, previous votes no longer apply"


def _maintainer_set(new_status, outcome):
    def handler(state, task, ev):
        if not _is_maintainer(state, ev["actor"]):
            raise Rejected("only maintainers can do this")
        if task.status in TERMINAL and new_status != AVAILABLE:
            raise Rejected(f"task is already {task.status}")
        if new_status == AVAILABLE and task.status not in TERMINAL | {BLOCKED}:
            raise Rejected(f"task is {task.status}, nothing to reopen")
        _end_attempt(task, state.clock, outcome)
        task.status, task.claimant, task.lease_expires = new_status, None, None
        task.block_reason = ev.get("reason") if new_status == BLOCKED else None
        return f"task is now {new_status}"
    return handler


def _block(state, task, ev):
    if ev["actor"] != task.claimant and not _is_maintainer(state, ev["actor"]):
        raise Rejected("only the claimant or a maintainer can block a task")
    if task.status in TERMINAL:
        raise Rejected(f"task is {task.status}")
    if not ev.get("reason"):
        raise Rejected("a reason is required")
    _end_attempt(task, state.clock, "blocked")
    task.status, task.claimant, task.lease_expires, task.block_reason = BLOCKED, None, None, ev["reason"]
    return "task blocked: " + ev["reason"]


HANDLERS = {
    "claim": _claim, "renew": _renew, "start": _start, "release": _release, "submit": _submit,
    "vote": _vote, "approve": _approve, "merged": _merged, "pr_closed": _pr_closed, "pr_updated": _pr_updated,
    "block": _block,
    "unblock": _maintainer_set(AVAILABLE, "unblocked"), "reopen": _maintainer_set(AVAILABLE, "reopened"),
    "reject": _maintainer_set(REJECTED, "rejected"), "cancel": _maintainer_set(CANCELLED, "cancelled"),
}
CONFIG_KINDS = {"policy", "task", "tick"}


def apply(state: State, ev: dict) -> dict | None:
    """Apply one journal entry. Returns the decision for requests, None otherwise."""
    if ev["id"] in state.seen:
        return None  # idempotent: replayed or duplicated events are ignored
    state.seen.add(ev["id"])
    t = parse_time(ev["time"])
    state.clock = t if state.clock is None else max(state.clock, t)  # logical clock never goes back
    _expire(state)
    kind = ev["kind"]
    if kind == "policy":
        state.policy = {**DEFAULT_POLICY, **ev["policy"],
                        "required_passes": {**DEFAULT_POLICY["required_passes"], **ev["policy"].get("required_passes", {})}}
        return None
    if kind == "task":
        d = ev["task"]
        if d["id"] in state.tasks:
            state.tasks[d["id"]].definition = d
        else:
            state.tasks[d["id"]] = Task(definition=d)
        return None
    if kind == "tick":
        return None
    decision = {"event": ev["id"], "task": ev.get("task"), "actor": ev.get("actor"), "kind": kind, "issue": ev.get("issue")}
    try:
        if kind not in HANDLERS:
            raise Rejected("unrecognised command; see PROTOCOL.md for the exact syntax")
        task = state.tasks.get(ev.get("task"))
        if task is None:
            raise Rejected(f"unknown task {ev.get('task')}")
        decision.update(accepted=True, message=HANDLERS[kind](state, task, ev))
    except Rejected as exc:
        decision.update(accepted=False, message=str(exc))
    state.decisions.append(decision)
    return decision


def fold(events, until: datetime | None = None) -> State:
    """Replay a journal. ``until`` advances the clock (e.g. to now) to expire stale leases."""
    state = State()
    for ev in events:
        apply(state, ev)
    if until is not None:
        state.clock = until if state.clock is None else max(state.clock, until)
        _expire(state)
    return state
