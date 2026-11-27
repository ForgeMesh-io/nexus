# ADR 001: Keep coordination off the project write path

**Status:** Accepted for the local pilot, not a migration decision. **Date:** 2026-11-26.

The baseline `97fbb27bb683ee41f851390aa6bdfc1e4d6fa424` already has a deterministic state machine, CAS journal, independent exact-SHA votes and locked-down validation tooling. Reuse those semantics and keep the existing workflow intact. Its `/fm` ingress, workflow replies and participant-opened PRs consume public GitHub capacity before Nexus accepts the work; adding a quota only after that ingress cannot contain those writes. The experimental `rust-port` changes the runtime, not this boundary.

| Option | Benefit | Reason not to lead with it |
| --- | --- | --- |
| Keep GitHub comments + Actions + Git CAS | No additional service; auditable history | Comments and agent-opened PRs bypass intake bounds; retries still consume GitHub traffic. |
| Git refs + distributed convergence (Grite/EvoGit style) | Offline work and portable history | Convergence/advisory locks are insufficient for hard admission and a shared mutation quota. A write authority would still be needed. |
| One self-hosted authority per pilot, SQLite on local disk | Transactions for leases, permissions, review, audit and quota; no external database | Single-writer bottleneck and local recovery obligations. Measure before adding replicas; no shared network filesystem. |
| Distributed scheduler or shared multi-tenant service | Possible capacity/availability gains | Extra trust and operational costs; no measured need. |

Start with SQLite, short transactions with `BEGIN IMMEDIATE`, and no execution of candidate text. Use a fixed-capacity approved task catalog and intentionally restrict the first artifact to an issue report selected by a maintainer. A scoped credential binds each request to one operator-enrolled identity and role; the reviewer must come from a different enrolled human owner, not merely a different credential. This is a control on provenance, not proof of human identity or of a reviewer actually doing the work. Audit events are transactional, bounded by the pilot workflow, and readable only to the operator; they are not tamper-proof against that operator. Lease times come from the host clock. Run SQLite on a local filesystem with restricted access and back it up using SQLite's backup interface, not live file copies.

## Minimum functional path

```text
maintainer selects issue + revision ───────┐
volunteer via client ─ reserve, submit ────┼──> one coordinator ──> SQLite
independent reviewer ─ exact digest ───────┘            │         state + audit
maintainer ─ authorize ────────────────────────────────┘
                    durable intent ──> separate publisher ──> one existing issue
                                                       <── reconcile by identity
```

Use an internal contract first. CLI is a reference transport for scripts/operators, not a promise to chat users. HTTP+JSON is the next lowest-common-denominator transport for headless clients; use authenticated HTTPS with request and concurrency limits before network exposure. MCP maps named tools to the same policy/operations for supported harnesses; local stdio and remote Streamable HTTP have different setup and trust requirements. A2A Agent Cards and asynchronous delegation make sense only if independently hosted agents actually need to delegate to each other. It would add little to a client claiming from a coordinator today. A browser/manual handoff can serve a tool-less chat without granting it an identity. No transport may implement its own authorization rules or silently fall back to GitHub writes.

## Target trajectory (not implemented)

```text
human consent -> CLI / web / MCP clients -> bounded per-project coordinator
                                          <- trusted repo policy / opt-in
                                          <- read-only project signals
                       independent isolated validation -> exact artifact decision
                       authorized outbox -> GitHub App writer -> GitHub
                       durable audit      <- authenticated read reconciliation
                       maintainer stop + revoke -> block dispatch / disable App
```

Keep publisher code and credentials out of all ordinary agent and candidate environments. Start with selected repositories and a single mutation type; the deployed App permission may be coarser than that operation, so isolate it and enforce the route in code. No service can stop an unrelated GitHub user or model using a pre-existing personal token from writing outside Nexus. Record intent and debit quota before attempting a GitHub mutation; a lost response is not permission to retry it. An uncertain write consumes quota until reconciled; an empty/missing read is not proof it did not occur. Stop prevents new intents/dispatch but cannot undo a request already handed to GitHub. Preserve human work and existing issues, branches, policies and installations on removal.

Revisit the decision if paired experiments show no review-load or goodput benefit, if measured write contention or restore time exceeds the deployment's agreed budget, or if an approved deployment needs more than one writing host. [SQLite's selection guide](https://www.sqlite.org/whentouse.html#checklist_for_choosing_the_right_database_engine) makes the same distinction between queued local writers and simultaneous writers that cannot take turns. Keep the ledger on the coordinator's local disk even if clients use a network transport. See the [research log](research.md).
