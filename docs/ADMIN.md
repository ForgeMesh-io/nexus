# Administration

Everyday operations for maintainers. All changes go through reviewed PRs unless stated otherwise.

## Tasks

- **Add**: PR adding `.forgemesh/tasks/<ID>.json`. Check with `python -m forgemesh check-config .`. The next coordinator run publishes it.
- **Edit**: PR changing the file. The coordinator records the new definition; existing claims stay valid.
- **Cancel / reject / reopen**: comment `/fm cancel <ID> <reason>`, `/fm reject <ID> <reason>`, `/fm reopen <ID>`.
- **Approve** a submission (medium+ risk or protected paths): review the PR, then `/fm approve <ID> <head-sha>`.

## Participants

- **Trusted validators**: edit `trusted_validators` in `policy.json`.
- **Abuse**: block the account at organisation level (Settings → Moderation → Blocked users). Their future comments are not visible to the coordinator's queries; past journal entries remain for audit.

## Pausing

Set `"paused": true` in `.forgemesh/policy.json` (emergency: push directly if rulesets allow admins to bypass, then open a PR for the record). New claims are refused; existing work can still be submitted and validated.

## Coordinator

- Logs: Actions → `forgemesh` workflow.
- Force a full re-scan: Actions → `forgemesh` → Run workflow → `full-scan`.
- Rebuild state: derived files are recomputed on every run from `journal.jsonl`.
- **Never** edit or force-push `forgemesh-state` by hand. If the journal must be corrected, append a compensating maintainer event (e.g. `/fm reopen`) instead.

## Updating NEXUS in a swarm

1. Pick a reviewed `nexus` commit SHA.
2. Update both `__NEXUS_SHA__` occurrences in the swarm's `.github/workflows/forgemesh.yml`.
3. Update `nexus_ref` in the swarm manifest and republish it in the registry.

## Releasing images

Push a signed tag `vX.Y.Z` on `nexus`; approve the `release` environment run; copy the digests from the run summary into the swarm manifests; republish manifests.

## Registry

- Online roles expire quickly (timestamp: 2 days, re-signed daily). The `registry` repository's scheduled workflow refreshes them; if it fails for more than two days, clients stop accepting the registry (fail-safe).
- Publish a manifest: `python dev_registry.py publish <swarm> <manifest.json>` (development); production uses the swarm key on the key holder's machine, then a PR.
