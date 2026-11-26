"""Trusted local operator interface; never expose this command to untrusted callers."""

import argparse
import inspect
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile

from .pilot import Pilot, PilotError


def publish_local(ledger, token, task, current_base, destination):
    if not isinstance(destination, str) or not Path(destination).is_dir():
        raise PilotError("invalid_destination")
    directory = Path(destination)
    payload = ledger.dispatched(token, task)
    if payload is None:
        payload = ledger.begin_dispatch(token, task, current_base)
        if payload is None:
            raise PilotError("no_dispatch")
        target = directory / (payload["marker"] + ".json")
        with tempfile.NamedTemporaryFile(dir=directory, mode="w", encoding="utf-8") as staged:
            json.dump(payload, staged, sort_keys=True)
            staged.flush()
            os.fsync(staged.fileno())
            os.link(staged.name, target)
    target = directory / (payload["marker"] + ".json")
    if not target.is_file() or target.stat().st_size > 65_536:
        raise PilotError("uncertain_dispatch")
    try:
        observed = json.loads(target.read_text(encoding="utf-8"))
    except (ValueError, RecursionError):
        raise PilotError("uncertain_dispatch") from None
    if observed != payload:
        raise PilotError("uncertain_dispatch")
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    # The local sink allows one publication per issue; the issue is its stable receipt ID.
    return ledger.record_publication(token, payload["marker"], payload["issue"])


def publish_github(ledger, token, task, bot_user_id):
    """The installation token comes only from NEXUS_GITHUB_TOKEN so it never reaches stdin, argv or output."""
    from .pilot_github import GitHubPublisher

    return GitHubPublisher(os.environ.get("NEXUS_GITHUB_TOKEN"), bot_user_id).publish(ledger, token, task)


def _object(pairs):
    result = dict(pairs)
    if len(result) != len(pairs):
        raise ValueError("duplicate key")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database")
    parser.add_argument("action", help="Local operator action (see docs/nexus-pilot/operators.md)")
    args = parser.parse_args()
    ledger = Pilot(args.database)
    commands = {
        "initialize": ledger.initialize, "enroll": ledger.enroll, "add-task": ledger.add_task,
        "discover": ledger.discover, "claim": ledger.claim, "submit": ledger.submit,
        "review": ledger.review, "inspect-report": ledger.inspect_report,
        "authorize": ledger.authorize, "decline": ledger.decline, "revoke": ledger.revoke,
        "stop": ledger.stop, "audit": ledger.audit,
        "publish-local": lambda **payload: publish_local(ledger, **payload),
        "publish-github": lambda **payload: publish_github(ledger, **payload),
    }
    try:
        if args.action not in commands:
            raise PilotError("unknown_action")
        raw = sys.stdin.buffer.read(65_537)
        if len(raw) > 65_536:
            raise PilotError("invalid_input")
        try:
            data = json.loads(raw, object_pairs_hook=_object)
            if not isinstance(data, dict):
                raise TypeError("expected object")
            command = commands[args.action]
            if args.action.startswith("publish-"):
                publisher = publish_local if args.action == "publish-local" else publish_github
                inspect.signature(publisher).bind(ledger, **data)
            else:
                inspect.signature(command).bind(**data)
        except (ValueError, TypeError, RecursionError):
            raise PilotError("invalid_input") from None
        print(json.dumps(command(**data)))
        return 0
    except PilotError as exc:
        print(json.dumps({"error": exc.code}))
    except (OSError, sqlite3.Error):
        print(json.dumps({"error": "storage_unavailable"}))
    return 1


if __name__ == "__main__":
    sys.exit(main())
