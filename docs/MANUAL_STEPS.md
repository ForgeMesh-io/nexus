# Manual steps

Things that cannot (or must not) be automated by an agent. Tick them in a tracking issue.

## Founder, once

- [ ] Run the production key ceremony ([KEY_CEREMONY.md](KEY_CEREMONY.md)); replace the development anchor everywhere.
- [ ] Find two other root key holders and a second maintainer (bus factor).
- [ ] Organisation: keep 2FA required; review members and outside collaborators quarterly.
- [ ] Create a `maintainers` team when there is more than one maintainer and switch CODEOWNERS to it.
- [ ] Configure required reviewers on the `release` environment of `nexus` (image publishing).

## Every swarm repository

- [ ] Ruleset on the default branch: block deletion and force push, require a pull request with 1 approval, require CODEOWNERS review, require status checks (CI), dismiss stale approvals.
- [ ] Ruleset on `forgemesh-state`: block deletion and force push (the coordinator pushes fast-forward only).
- [ ] Settings → Actions → General: "Read repository contents" default token permission; do not allow Actions to approve pull requests; require approval for workflows from first-time contributors (all outside contributors for sensitive swarms).
- [ ] Secret scanning, push protection, Dependabot alerts, private vulnerability reporting: enabled.
- [ ] Create and pin the "ForgeMesh coordination" issue.
- [ ] Replace `__NEXUS_SHA__` in `.github/workflows/forgemesh.yml`.

## Rust coordinator pilot

- After reviewing the migration and its CI, pin both the reusable workflow and its `nexus-ref` to the same reviewed NEXUS commit. Set `rust-coordinator: true` on one swarm only. Verify the first run, including task decisions and replies, before changing another caller.
- To roll back, remove `rust-coordinator: true` or restore the previous caller pins. Keep the `forgemesh-state` branch intact. The Python coordinator can replay the Rust journal; do not rewind it to undo a config or task decision.

## Registry

- [ ] Create the `online-keys` environment on `registry` (deployment branches: `main` only, no required reviewers so the daily re-signing is never blocked) and store the online keys (`snapshot`, `timestamp`) as its secrets `SNAPSHOT_KEY` and `TIMESTAMP_KEY`. Set the repository variable `NEXUS_REF` to the pinned nexus commit.
- [ ] Check that the scheduled refresh runs; timestamp metadata expires after 2 days.

## ORBIS

- [ ] Decide which upstream PR clusters to integrate first (see `FORGEMESH.md` in the fork).
- [ ] Before proposing anything upstream: read upstream's contribution and AI-disclosure rules, propose one change at a time, never in bulk.

## VIE

- [ ] Legal review before any code: no Microsoft SDKs, keys, firmware, game files or leaked material in the repository or in tasks.
