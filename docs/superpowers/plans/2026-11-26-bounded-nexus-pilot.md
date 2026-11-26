# Bounded Nexus Pilot Implementation Plan

> **For agentic workers:** Execute task-by-task, with a red test before each implementation and a green suite before moving on.

**Goal:** Demonstrate a maintainer-authorized, bounded report contribution cycle without letting participants write to GitHub.

**Architecture:** An isolated local SQLite authority followed by a separate dispatch step. Maintain the current GitHub-native flow until both systems have comparable end-to-end evidence.

**Tech Stack:** Python 3.12, SQLite, pytest; no new runtime dependency for the ledger.

**Spec:** [Mission](../../nexus-pilot/mission.md), [ADR 001](../../nexus-pilot/adr-001-coordination.md).

## Global constraints

One public repository per install, local database, explicit opt-in. No candidate execution. No automatic merge, new issues or PRs. No GitHub credential in participant traffic. Stop on ambiguous remote writes. Use isolated sandbox for code checks, not a GitHub validation vote.

## Review focus

Race for the same task or last slot; stale token after lease transfer; different credentials for the same human owner; review bound to a different digest; permission revocation between review and dispatch; crash between recording the intent and observing GitHub acceptance.

### 1. Local ledger

Files: `forgemesh/pilot.py`, `tests/test_pilot.py`. `Pilot(path, clock=...)` exposes `initialize`, `enroll`, `add_task`, `discover`, `claim`, `submit`, `review`, `revoke`, `stop`, `audit`. Application errors carry a stable `PilotError.code`.

- [ ] Run `python -m pytest -q -p no:cacheprovider tests/test_pilot.py` before implementation. Tests cover concurrent claims, backpressure, lease expiry/fencing, exact retries, independent review, stop/revoke and audit on reopen.
- [ ] Use a short SQLite transaction for each mutation. Authenticate against stored token hashes, enforce one active lease per volunteer and fixed ceilings, preserve the old lease on backpressure, and record only accepted transitions without storing plaintext credentials.
- [ ] Re-run targeted tests plus the baseline suite and `python -m forgemesh check-config .`.

### 2. Dispatch and participant entry point

Files: `forgemesh/pilot.py`, `forgemesh/pilot_cli.py`, `tests/test_pilot.py`, `tests/test_pilot_cli.py`, pilot operator guide.

- [ ] Red tests: concurrent approval of the last quota unit, non-authorizer, stopped/withdrawn intent, stale base, crash before/after request, uncertainty and reconciliation without another send.
- [ ] Authorize exact reviewed content separately from review. Use a total installation quota consumed atomically and never implicitly refunded, one dispatch owner and one attempt per artifact. Revisit quota windows only with measurements.
- [ ] Expose a small local JSON/CLI contract and run a full scenario with separate identities. GitHub-reaching code must have its own credential, operate on the configured repo/issue only, and must not be enabled remotely until authorized.

### 3. Live proof and release gate

- [ ] Add and verify authorized fixture publication, reconciliation, stale policy, refusal and removal. Test retries and permissions on the same integration path used by operators. Preserve normal human workflow.
- [ ] Test actual OpenCode and one other client in clean setup; document unconnected chat fallback in the same guide. Record the fixed-budget comparison using the [research protocol](../../nexus-pilot/research.md).
- [ ] Update the [evidence register](../../nexus-pilot/evidence.md) with exact commands and outcomes. Do not declare a public release on the strength of a local proof.
