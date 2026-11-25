# Architecture decisions

Each entry: context, decision, consequences. Newest last.

## D1 — One repository per trust domain

Repositories: `registry` (trust root, portal), `nexus` (protocol + tooling + reusable workflows), `vie`, `anyps5` (ORBIS fork).
A compromised swarm repository cannot rewrite the registry or another swarm's rules.

## D2 — Task coordination is an event-sourced log stored in Git

- Requests come in as GitHub issue comments (`/fm claim`, `/fm submit`, ...). Comments are an *inbox*, not the source of truth: they can be edited or deleted.
- A trusted workflow ingests new comments into an append-only `journal.jsonl` on the swarm repository's `forgemesh-state` branch. Ingestion order (journal order) is the canonical total order.
- The task state is a pure, deterministic fold over the journal (`forgemesh.state.fold`). Any run, on any machine, computes the same state from the same journal.
- Writes use Git's compare-and-swap: a push that is not a fast-forward is rejected, the writer re-fetches, re-ingests and retries. `concurrency:` in GitHub Actions is only an optimisation; correctness does not depend on it (runs can be cancelled or dropped).
- A scheduled reconciliation run re-reads all comments, so a lost or cancelled run only delays processing.
- Because the fold is append-only, a decision (e.g. who won a claim) never flips after it has been published.

Consequences: no server, no database; full audit trail in Git; throughput is bounded by GitHub Actions latency (seconds to minutes), which is acceptable for tasks lasting hours.

## D3 — Time comes from GitHub, not from agents

Event time is the comment `created_at` set by GitHub. Lease expiry is evaluated against a monotonic logical clock (`max(event_time, previous_time)`), so agents cannot back-date requests.

## D4 — Independent validation, risk-based

An author can never validate their own submission. Votes are bound to the submitted head SHA; a new push invalidates previous votes. Required passes: low 1, medium 2, high 2 + maintainer approval, critical 3 + maintainer approval. Distinct GitHub accounts are not proof of independence: high/critical also require at least one vote from the swarm's trusted validator list and a green trusted CI run (branch protection).

## D5 — Native GitHub protections over custom enforcement

Protected paths (policy, workflows, acceptance tests) are enforced by CODEOWNERS + rulesets (required code-owner review), not by ForgeMesh code. ForgeMesh code only *reports* violations; GitHub *enforces* them. Agents never receive write access to protected branches.

## D6 — Trust root: TUF, anchored by the SHA-256 of `root.json`

The registry is a TUF repository served by GitHub Pages. Each swarm is a delegated targets role restricted to `swarms/<name>/*`. The participation prompt carries the SHA-256 of the initial `root.json`; the agent checks it with the OS `sha256sum` before trusting anything, then uses the reference `python-tuf` client. Root keys are offline, threshold 2-of-3 in production. Development keys are generated locally, labelled `DEV`, never committed.

## D7 — Container images: pinned by digest in signed manifests, provenance via GitHub artifact attestations

Images live on GHCR. Swarm manifests (TUF-signed) pin images by `sha256` digest, so substitution is detected by the digest itself. Build provenance uses `actions/attest-build-provenance` (verifiable with `gh attestation verify`, no extra tool for participants). Cosign remains compatible (Sigstore bundles) but is not required.

## D8 — Untrusted code runs only in a locked-down container by default

`--network none`, `--cap-drop ALL`, `no-new-privileges`, read-only root, non-root user, resource limits, only a throw-away copy of the workspace mounted. Never the home directory, the Docker socket or credentials. Native execution is opt-in, per task, and only for code whose provenance is verified. Docker is not treated as a hard security boundary: risky tasks require the ISOLATED (VM) mode.

## D9 — Python standard library first

The coordinator and agent CLI use only the standard library, plus `jsonschema` (validation) and `tuf` (registry). No web framework, no database, no daemon.

## D10 — Licences

ForgeMesh (nexus, registry, vie): Apache-2.0. ORBIS fork of AnyPS5 stays GPL-2.0 as required by upstream.
