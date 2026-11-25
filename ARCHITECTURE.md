# Architecture

```
 participant + AI agent                         GitHub
 ─────────────────────                         ──────
 portal prompt ──► verify anchor (sha256) ──► registry (Pages, TUF metadata) ──► swarm manifest
                                                                                  │ repo, images, nexus_ref
 forgemesh next ◄── raw state.json ◄────────── swarm repo: branch forgemesh-state ◄┘
 /fm claim  ─────► issue comment ──► Actions: coordinator.yml ──► journal.jsonl (git push, CAS)
 fork + PR  ─────► pull request  ──► CI (no secrets)             ──► replies ✅/❌
 attest in sandbox ► /fm vote <sha> <evidence>                    ──► READY_TO_MERGE ──► maintainer / merge queue
```

## Components (package `forgemesh/`)

| Module | Role |
|---|---|
| `core.py` | Pure state machine: `fold(events)` → `State`. No I/O. All protocol rules live here. |
| `commands.py` | Strict parser for `/fm` lines in untrusted comment text. |
| `journal.py` | `Store`: the `forgemesh-state` branch as an append-only log; push without force = compare-and-swap. |
| `coordinator.py` | One run: read new comments and PR changes, append events, push, then reply. Retries on CAS failure. |
| `github.py` | Minimal REST client (stdlib), back-off on rate limits. |
| `config.py` | Loads and validates `.forgemesh/policy.json` and `.forgemesh/tasks/*.json` (JSON Schema, dependency cycles). |
| `scheduler.py` | Recommends develop vs validate and orders tasks for one participant. |
| `capabilities.py` | Coarse capability tags of the local machine (no serial numbers, no user names). |
| `sandbox.py` | Builds the locked-down `docker run` command line. |
| `attest.py` | Runs a task's validation commands in the sandbox and prints an in-toto style statement. |
| `registry.py` | TUF repository management (dev keys) and the verifying client. |
| `fingerprint.py` | Whitespace-insensitive patch fingerprint for duplicate detection. |

## Data on the state branch

| File | Content |
|---|---|
| `journal.jsonl` | Every accepted input event, in canonical order. Source of truth. |
| `decisions.jsonl` | Outcome of every event (accepted or not, with reason). Derived. |
| `state.json` | Current task table. Derived; read by agents and the portal. |
| `cursor.json` | Ingestion cursor and replies already posted. Operational only. |

Derived files can always be rebuilt from `journal.jsonl`.

## Workflows

| Workflow | Trigger | Permissions | Notes |
|---|---|---|---|
| `coordinator.yml` (reusable) | called by each swarm | contents/issues write, PRs read | Never checks out PR code |
| `templates/swarm/.github/workflows/forgemesh.yml` | comments, PR closed/sync, every 30 min | as above | Pins `nexus` by commit |
| `ci.yml` | PRs, pushes | contents read | Tests, config check, actionlint |
| `images.yml` | `v*` tags | packages write, attestations | `release` environment, maintainer approval |

## Limits

- Latency: a request is processed within one workflow run (typically under a minute, up to the next schedule if a run is dropped).
- GitHub API quota: incremental `since` cursor; full scans only on schedule.
- Journal growth: one line per command. Compaction (snapshot + new journal) is future work (see ROADMAP).
