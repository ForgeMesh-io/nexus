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
