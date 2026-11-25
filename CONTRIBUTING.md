# Contributing

Contributions go through the ForgeMesh protocol, even for ForgeMesh itself.

1. Read [AGENTS.md](AGENTS.md) (applies to humans too) and [PROTOCOL.md](PROTOCOL.md).
2. Find a task: `python -m forgemesh next --repo ForgeMesh-io/nexus --actor <login>`, or browse `.forgemesh/tasks/`.
3. Claim it by commenting `/fm claim <ID>` on the pinned coordination issue. Wait for ✅.
4. Fork, branch `fm/<ID>-<slug>`, keep the change small and inside the task's scope.
5. Run `python -m pytest -q` (or the task's validation commands in the sandbox).
6. Open a PR with the template, then comment `/fm submit <ID> #<PR>`.

**New task ideas**: open a PR adding `.forgemesh/tasks/<ID>.json` (next free number). A maintainer reviews it; tasks are protected paths.

**Everything in English**: code, comments, docs, commits, PRs, issues.

**Commit messages**: imperative mood, ≤ 72 characters subject, task id in the PR title.

**AI assistance** is expected; disclose the agent and model in the PR.

**Licence**: by contributing you agree that your contribution is licensed under Apache-2.0 (inbound = outbound). Web commits require sign-off.

**Security issues**: private vulnerability reporting only, see [SECURITY.md](SECURITY.md).

## Rust build profiles

Prefer Rust for ForgeMesh tooling and new components. For a new Rust workspace, copy the profile blocks from [`Cargo.toml`](Cargo.toml) to the workspace root. Do not rewrite an upstream fork solely to change its language.

The Rust binary is available for local testing. Existing swarms still run the pinned Python coordinator and use the TUF client. Do not change a caller's pin until a maintainer reviews replay parity and verifies the rollback plan.

| Profile | Command | Purpose |
|---|---|---|
| `fast` | `cargo test --locked --profile fast` | Quick incremental tests, unoptimized, with line tables. |
| `release` | `cargo build --locked --release` | Portable artifacts with optimization level 3, fat LTO, one codegen unit, abort-on-panic, and stripped symbols. |

For a benchmark on one machine, `RUSTFLAGS='-C target-cpu=native' cargo build --locked --release` enables CPU-specific tuning. Do not publish those builds as portable releases. Consider PGO only when repeatable representative workloads show a measured benefit; keep it out of the default profile.

On Linux, pull and verify the registry-pinned image first. Rust `forgemesh sandbox --image <digest> --source <checkout> -- <command>` uses a disposable workspace. Rust `forgemesh attest --task-file <task> --source <checkout> --image <digest>` tests a Git archive of `HEAD`, omits raw logs, and never runs native validation. Git archives do not include submodules and honor `export-ignore` and `export-subst`; use the existing workflow for tasks that require a complete recursive checkout. GPU access requires separate per-task approval and `--gpu`. Never keep credentials or private inputs in any sandbox source tree.
