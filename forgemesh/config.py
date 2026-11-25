"""Load and validate a swarm's configuration (.forgemesh/ on the default branch)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import jsonschema

SCHEMAS = Path(__file__).parent / "schemas"


def _schema(name: str) -> dict:
    return json.loads((SCHEMAS / f"{name}.schema.json").read_text())


def validate(obj: dict, name: str) -> None:
    jsonschema.validate(obj, _schema(name), cls=jsonschema.Draft202012Validator)


def load(root: Path) -> tuple[dict, list[dict]]:
    """Return (policy, tasks) from <root>/.forgemesh. Raises on any invalid file."""
    base = Path(root) / ".forgemesh"
    policy = json.loads((base / "policy.json").read_text())
    validate(policy, "policy")
    tasks, ids = [], set()
    for p in sorted((base / "tasks").glob("*.json")):
        t = json.loads(p.read_text())
        validate(t, "task")
        if t["swarm"] != policy["swarm"]:
            raise ValueError(f"{p.name}: swarm '{t['swarm']}' does not match policy '{policy['swarm']}'")
        if p.stem != t["id"]:
            raise ValueError(f"{p.name}: file name must be <id>.json")
        if t["id"] in ids:
            raise ValueError(f"duplicate task id {t['id']}")
        ids.add(t["id"])
        tasks.append(t)
    for t in tasks:
        for d in t.get("depends_on", []):
            if d not in ids:
                raise ValueError(f"{t['id']}: unknown dependency {d}")
    _check_cycles(tasks)
    return policy, tasks


def _check_cycles(tasks: list[dict]) -> None:
    deps = {t["id"]: t.get("depends_on", []) for t in tasks}
    done, stack = set(), set()

    def visit(n):
        if n in stack:
            raise ValueError(f"dependency cycle through {n}")
        if n in done:
            return
        stack.add(n)
        for d in deps[n]:
            visit(d)
        stack.discard(n)
        done.add(n)

    for n in deps:
        visit(n)


def digest(obj: dict) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def config_events(policy: dict, tasks: list[dict], journal: list[dict], now: str) -> list[dict]:
    """Events needed to bring the journal's view of the configuration up to date."""
    current_policy, current_tasks = None, {}
    for e in journal:
        if e["kind"] == "policy":
            current_policy = e["policy"]
        elif e["kind"] == "task":
            current_tasks[e["task"]["id"]] = e["task"]
    out = []
    if current_policy != policy:
        out.append({"id": f"cfg:policy:{digest(policy)[:16]}:{len(journal)}", "kind": "policy", "time": now,
                    "actor": "@system", "policy": policy})
    for t in tasks:
        if current_tasks.get(t["id"]) != t:
            out.append({"id": f"cfg:task:{t['id']}:{digest(t)[:16]}:{len(journal)}", "kind": "task", "time": now,
                        "actor": "@system", "task": t})
    return out
