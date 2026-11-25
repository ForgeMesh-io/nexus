"""Deterministic, capability-aware task recommendation with validation back-pressure."""

from __future__ import annotations

import hashlib

from .core import CLAIMABLE, IN_REVIEW, SUBMITTED, VALIDATING, State, Task

REVIEW_TYPES = {"reviewer", "validator", "challenger", "integrator", "benchmarker", "security"}


def dev_share(state: State) -> float:
    """Fraction of participants that should develop rather than validate."""
    vp = {"low_queue": 3, "high_queue": 10, "dev_share_low": 0.7, "dev_share_mid": 0.35, "dev_share_high": 0.05,
          **state.policy.get("validation_pressure", {})}
    q = state.validation_queue()
    if q <= vp["low_queue"]:
        return vp["dev_share_low"]
    if q >= vp["high_queue"]:
        return vp["dev_share_high"]
    return vp["dev_share_mid"]


def mode_for(state: State, actor: str, salt: str) -> str:
    """Stable per-participant split: the same actor gets the same answer for the same salt (e.g. the day)."""
    if state.validation_queue() == 0:
        return "develop"
    bucket = int(hashlib.sha256(f"{actor}|{salt}".encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
    return "develop" if bucket < dev_share(state) else "validate"


def _blocks_count(state: State, task: Task) -> int:
    return sum(1 for t in state.tasks.values() if task.id in t.definition.get("depends_on", []))


def recommend(state: State, actor: str, capabilities: set[str], salt: str = "", limit: int = 5) -> dict:
    mode = mode_for(state, actor, salt)
    validate = []
    for t in state.tasks.values():
        if t.status in {SUBMITTED, VALIDATING} and t.submission and actor not in (t.claimant, t.submission["author"]) \
                and actor not in t.votes and set(t.definition.get("hardware", [])) <= capabilities:
            age = t.submission.get("at", "")
            validate.append((t.definition["priority"], age, t.id))
    validate.sort()
    develop = []
    for t in state.tasks.values():
        d = t.definition
        if t.status not in CLAIMABLE or not state.deps_satisfied(t) or state.conflicts(t):
            continue
        if not set(d.get("hardware", [])) <= capabilities:
            continue
        if any(state.component_load(c) >= state.policy["wip_limit_per_component"] for c in d.get("components", [])):
            continue
        review_bonus = 0 if (mode == "validate" and d["type"] in REVIEW_TYPES) else 1
        rare_hw = -len(d.get("hardware", []))  # prefer tasks that need what this participant has
        develop.append((review_bonus, d["priority"], -_blocks_count(state, t), rare_hw, t.id))
    develop.sort()
    return {
        "mode": mode,
        "validation_queue": state.validation_queue(),
        "in_review": sum(1 for t in state.tasks.values() if t.status in IN_REVIEW),
        "validate": [x[-1] for x in validate[:limit]],
        "claim": [x[-1] for x in develop[:limit]],
        "paused": bool(state.policy.get("paused")),
    }
