"""ForgeMesh command line.

Agent side (read-only, no token needed):
    python -m forgemesh capabilities
    python -m forgemesh next --repo OWNER/REPO --actor LOGIN
    python -m forgemesh status --repo OWNER/REPO [--task ID]
Maintainer / CI side:
    python -m forgemesh check-config [ROOT]
    python -m forgemesh coordinate --repo OWNER/REPO --state-dir DIR [--config-root ROOT] [--full-scan]
    python -m forgemesh sandbox --image NAME@sha256:... --source DIR -- CMD...
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from . import capabilities, config, sandbox, scheduler
from .core import fold
from .journal import BRANCH, read_jsonl


def _journal(repo: str) -> list[dict]:
    url = f"https://raw.githubusercontent.com/{repo}/{BRANCH}/journal.jsonl"
    try:
        with urllib.request.urlopen(url, timeout=60) as r:
            text = r.read().decode()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return []
        raise
    return [json.loads(x) for x in text.splitlines() if x.strip()]


def _load_events(args) -> list[dict]:
    return read_jsonl(Path(args.journal)) if args.journal else _journal(args.repo)


def cmd_next(args) -> int:
    caps = set(args.capability or ([] if args.no_execution else capabilities.detect()["tags"]))
    state = fold(_load_events(args), until=datetime.now(timezone.utc))
    salt = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    rec = scheduler.recommend(state, args.actor, caps, salt=salt, no_execution=args.no_execution)
    rec["tasks"] = {tid: {**state.tasks[tid].definition, "status": state.display_status(state.tasks[tid])}
                    for tid in rec["validate"] + rec["claim"]}
    print(json.dumps(rec, indent=2))
    return 0


def cmd_status(args) -> int:
    state = fold(_load_events(args), until=datetime.now(timezone.utc))
    data = state.to_json()
    if args.task:
        data = data["tasks"].get(args.task) or {"error": "unknown task"}
    print(json.dumps(data, indent=2))
    return 0


def cmd_check_config(args) -> int:
    policy, tasks = config.load(Path(args.root))
    print(f"OK: swarm '{policy['swarm']}', {len(tasks)} task(s)")
    return 0


def cmd_coordinate(args) -> int:
    from .coordinator import Coordinator
    from .github import GitHub
    from .journal import Store
    policy, tasks = config.load(Path(args.config_root))
    result = Coordinator(GitHub(args.repo), Store(Path(args.state_dir)), policy, tasks).run(full_scan=args.full_scan)
    print(json.dumps(result))
    return 0


def cmd_sandbox(args) -> int:
    cmd = args.cmd[1:] if args.cmd and args.cmd[0] == "--" else args.cmd
    r = sandbox.run(args.image, Path(args.source), cmd, cpus=args.cpus, memory=args.memory,
                    timeout_s=args.timeout, gpu=args.gpu)
    sys.stdout.write(r.stdout)
    sys.stderr.write(r.stderr)
    return r.returncode


def cmd_attest(args) -> int:
    from . import attest
    task = json.loads(Path(args.task_file).read_text())
    config.validate(task, "task")
    image = args.image or task.get("validation", {}).get("image")
    if not image:
        print("no image: pass --image or set validation.image in the task", file=sys.stderr)
        return 2
    report = attest.run(task, Path(args.source), image)
    print(json.dumps(report, indent=2))
    return 0 if report["predicate"]["passed"] else 1


def cmd_verify(args) -> int:
    from . import registry
    base = args.registry.rstrip("/")
    try:
        data = registry.fetch_verified(f"{base}/metadata/", f"{base}/targets/", args.anchor, args.swarm,
                                       "manifest.json", Path(args.cache).expanduser() / args.anchor[:16])
        manifest = json.loads(data)
        config.validate(manifest, "manifest")
        if manifest["swarm"] != args.swarm:
            raise registry.TrustError("manifest is for another swarm")
        if manifest["status"] == "revoked":
            raise registry.TrustError("swarm is revoked")
    except (registry.TrustError, ValueError) as e:
        print(f"VERIFICATION FAILED: {e}\nStop and tell your human.", file=sys.stderr)
        return 3
    print(json.dumps(manifest, indent=2))
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="forgemesh")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("capabilities", help="print local capability tags")
    s.set_defaults(func=lambda a: print(json.dumps(capabilities.detect(), indent=2)) or 0)
    for name, func in (("next", cmd_next), ("status", cmd_status)):
        s = sub.add_parser(name)
        s.add_argument("--repo")
        s.add_argument("--journal", help="local journal.jsonl instead of fetching from GitHub")
        if name == "next":
            s.add_argument("--actor", required=True)
            s.add_argument("--capability", action="append", help="override detected capability tags")
            s.add_argument("--no-execution", action="store_true", help="only suggest read-only tasks and skip capability detection")
        else:
            s.add_argument("--task")
        s.set_defaults(func=func)
    s = sub.add_parser("check-config")
    s.add_argument("root", nargs="?", default=".")
    s.set_defaults(func=cmd_check_config)
    s = sub.add_parser("coordinate")
    s.add_argument("--repo", required=True)
    s.add_argument("--state-dir", required=True)
    s.add_argument("--config-root", default=".")
    s.add_argument("--full-scan", action="store_true")
    s.set_defaults(func=cmd_coordinate)
    s = sub.add_parser("sandbox")
    s.add_argument("--image", required=True)
    s.add_argument("--source", required=True)
    s.add_argument("--cpus", type=float, default=2)
    s.add_argument("--memory", default="4g")
    s.add_argument("--timeout", type=int, default=3600)
    s.add_argument("--gpu", action="store_true")
    s.add_argument("cmd", nargs=argparse.REMAINDER)
    s.set_defaults(func=cmd_sandbox)
    s = sub.add_parser("attest", help="run a task's validation commands in the sandbox, print an attestation")
    s.add_argument("--task-file", required=True)
    s.add_argument("--source", required=True, help="git checkout of the commit under test")
    s.add_argument("--image")
    s.set_defaults(func=cmd_attest)
    s = sub.add_parser("verify", help="verify a swarm manifest through the official TUF registry")
    s.add_argument("--registry", required=True, help="base URL, e.g. https://forgemesh-io.github.io/registry")
    s.add_argument("--anchor", required=True, help="SHA-256 of 1.root.json from the participation prompt")
    s.add_argument("--swarm", required=True)
    s.add_argument("--cache", default="~/.cache/forgemesh/tuf")
    s.set_defaults(func=cmd_verify)
    args = p.parse_args(argv)
    if getattr(args, "repo", None) is None and getattr(args, "journal", None) is None and args.cmd in ("next", "status"):
        p.error("--repo or --journal is required")
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
