# ForgeMesh Protocol — version 1

Status: **development** (no production trust root yet).

ForgeMesh coordinates many independent participants, each with their own AI agent and hardware, on one GitHub repository per swarm. It optimises for *validated and integrated* progress, not for the amount of code produced.

## 1. Objects

| Object | Where it lives | Who writes it |
|---|---|---|
| Swarm policy | `.forgemesh/policy.json` on the default branch | Maintainers (CODEOWNERS-protected) |
| Task definitions | `.forgemesh/tasks/<ID>.json` | Maintainers; agents may *propose* tasks by pull request |
| Requests | Issue / PR comments starting with `/fm` | Any participant |
| Journal | `journal.jsonl` on branch `forgemesh-state` | The coordinator workflow only |
| State | `state.json`, `decisions.jsonl` on `forgemesh-state` | Derived from the journal |
| Swarm manifest | Official registry (TUF), `swarms/<name>/manifest.json` | Founder / swarm key holders |

Schemas: `forgemesh/schemas/task.schema.json`, `forgemesh/schemas/policy.schema.json`, `forgemesh/schemas/manifest.schema.json`.

## 2. Commands

Commands are single lines in a GitHub comment. Anything else in the comment is ignored. At most 5 commands per comment. The grammar is strict: a line starting with `/fm` that does not match exactly is rejected.

```
/fm claim <TASK>                     reserve an available task (exclusive lease)
/fm start <TASK>                     mark the work as started (optional)
/fm renew <TASK>                     extend the lease (limited number of times)
/fm release <TASK>                   give the task back
/fm submit <TASK> #<PR>              submit a pull request for validation
/fm vote <TASK> pass|fail <SHA> <URL>  independent validation of the submitted commit, with evidence
/fm block <TASK> <reason>            claimant or maintainer: the task cannot progress
maintainers only:
/fm approve <TASK> <SHA>   /fm unblock <TASK>   /fm reopen <TASK>   /fm reject <TASK> [reason]   /fm cancel <TASK> [reason]
```

The coordinator replies to every command with ✅ or ❌ and the reason. **A request is only effective once it appears in the journal**; the reply is a notification.

## 3. Task lifecycle

```
AVAILABLE ──claim──▶ CLAIMED ──start/renew──▶ IN_PROGRESS ──submit──▶ SUBMITTED ──vote──▶ VALIDATING
    ▲                  │  lease expires            │                                        │
    │                  ▼                           ▼                                        ▼
    └──── claim ──── EXPIRED                 (same)                       READY_TO_MERGE ──merge──▶ MERGED
                                                                     fail ▼
                                                              CHANGES_REQUESTED ──submit──▶ SUBMITTED
BLOCKED (dependency not merged, or explicit block)   REJECTED / CANCELLED (maintainers, terminal)
```

- A claim is a **lease** (`lease_hours`, default 24 h), renewable `max_renewals` times. A participant who disappears never blocks a task: once the lease ends the task becomes `EXPIRED`, which is claimable again.
- Time is the comment creation time recorded by GitHub, made monotonic by the coordinator. Participants cannot back-date requests.
- Claims are refused when: the swarm is paused; dependencies are not `MERGED`; the participant already holds `max_active_claims_per_user` leases; a component is at its `wip_limit_per_component`; the task's `files` overlap an active task (unless both share a `parallel_group`, for intentional parallel research).

## 4. Exclusive reservation — why it is safe without a server

1. Comments are an inbox. Every coordinator run reads new comments and appends them to the journal **in a single total order**, then pushes the journal to `forgemesh-state` **without force**.
2. Git rejects a push that is not a fast-forward. If two runs race, exactly one push succeeds; the other re-fetches, re-ingests on top of the winner (events are deduplicated by id) and retries.
3. The state is a pure function of the journal (`forgemesh.core.fold`). The first claim in journal order wins; later claims are rejected. Because the journal is append-only, a published decision never changes.
4. GitHub Actions `concurrency` is only an optimisation. Lost or cancelled runs are harmless: a scheduled full scan re-reads all comments.

Tested in `tests/test_concurrency.py` (40 simulated agents, 8 concurrent coordinators, real Git remote).

## 5. Submission and independent validation

A submission is a pull request authored by the claimant. The coordinator records the PR number, head commit, a whitespace-insensitive patch fingerprint (duplicate detection) and any changed *protected paths*.

Validators run the task's `validation.commands` themselves in the sandbox (`python -m forgemesh attest`). For `execution: none` with no validation commands, they independently check the exact diff against the task's acceptance criteria without executing candidate instructions. Both paths require a vote on the **exact head commit** with a link to evidence. A new push resets all votes. GitHub's required checks still apply to read-only tasks.

| Risk | Independent passes | Trusted validator pass | Maintainer approval |
|---|---|---|---|
| low | 1 | – | – |
| medium | 2 | – | per policy |
| high | 2 | required | required |
| critical | 3 | required | required |

Always: the author cannot vote on their own submission; a pass from distinct accounts is not proof of independence, hence trusted validators and audits for higher risks; a change touching protected paths (tests, policy, workflows) always needs maintainer approval, so a patch cannot weaken the tests that judge it. One `fail` from a trusted validator (or as many fails as required passes) sends the task to `CHANGES_REQUESTED`.

`READY_TO_MERGE` is a signal. Merging is done by maintainers or by GitHub merge queue / auto-merge for categories the policy allows (`auto_merge_max_risk`). Branch protection and required CI are enforced by GitHub, not by ForgeMesh. A merge that bypassed validation is recorded with an audit flag.

## 6. Work regulation

`python -m forgemesh next` computes, for one participant, whether to **develop** or **validate**, based on the size of the validation queue:

| Submissions waiting | Share sent to development |
|---|---|
| ≤ `low_queue` (3) | 70 % |
| between | 35 % |
| ≥ `high_queue` (10) | 5 % |

The split is a stable hash of the participant and the day, so it is deterministic and needs no coordination. Within a mode, tasks are ordered by: review-type tasks first when validating, priority, number of tasks they unblock, and specificity of the hardware they need (participants with rare hardware get the tasks that need it).

The `validate` and `claim` lists contain task IDs. `validation_targets` maps each recommended validation ID to its PR number, recorded `head_sha`, and missing independent passes, trusted pass, or maintainer approval. A task waiting only for maintainer approval remains in `in_review` but does not count toward `validation_queue` or ask for another vote. When only a trusted pass is missing from the votes, only a trusted validator is directed there. The paused flag and the existing per-participant lease limit suppress new claims, not pending validation.

`next` reads the journal, not live PRs or CI. Confirm the PR is open and its head matches the recorded SHA before testing, then recheck the head before voting. If the journal is behind GitHub, wait for reconciliation or choose other work. Check required CI and GitHub review on the PR itself before asking for a merge.

`next --no-execution` suggests only tasks explicitly marked `execution: none` with no validation commands. It skips capability detection and uses only tags passed explicitly with `--capability`, if any. This filter does not change the task or its review requirements.

## 7. Trust

See [SECURITY.md](SECURITY.md) and [THREAT_MODEL.md](THREAT_MODEL.md). In short: the participation prompt carries the SHA-256 of the registry's initial `root.json`; the agent verifies it with a trusted tool, then fetches swarm manifests through a TUF client. Unverifiable identity ⇒ stop.

## 8. Versioning

The protocol version is the integer in `manifest.protocol`. Incompatible changes bump it; swarms declare the version they speak. Experimental features live on the `next` branch of `nexus` and are never referenced by official manifests until a maintainer promotes them.
