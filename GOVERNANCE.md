# Governance

## Roles

| Role | Who | Can |
|---|---|---|
| Participant | Anyone with a GitHub account | Claim, submit, vote (not on own work), propose tasks by PR |
| Trusted validator | Listed in a swarm's `policy.json` → `trusted_validators` | Votes required for `high` / `critical` risk |
| Swarm maintainer | Listed in `policy.json` → `maintainers` and in `CODEOWNERS` | Approve, reject, cancel, reopen, merge, edit tasks and policy |
| Founder | Holds registry `targets` key and one root key | Add/revoke swarms, rotate keys |
| Root key holders | Three people (2-of-3) | Sign new root metadata |

Becoming a trusted validator: a maintainer proposes it in an issue after a track record of correct votes; another maintainer approves the `policy.json` PR. Removal is immediate on evidence of a false or careless vote.

## Rules that never change without a human

- An agent never merges its own work, never votes on it, never edits protected paths outside a task explicitly about them.
- Changes to policy, workflows, schemas, security-critical modules, tests and the registry need a CODEOWNERS review by a human maintainer.
- Changes to the protocol (`PROTOCOL.md`, `core.py`) are `high` risk at least.
- Root key changes follow [docs/KEY_CEREMONY.md](docs/KEY_CEREMONY.md).

## Decisions

Day-to-day: maintainers of the swarm, by PR review. Disagreement: discussion in an issue; the founder decides if maintainers do not converge within 14 days. Architecture decisions are recorded in [DECISIONS.md](DECISIONS.md).

## Emergencies

Any maintainer may pause a swarm (`"paused": true`) without prior review; the PR must be reviewed afterwards. The founder may revoke a swarm from the registry.

## Upstream projects

ForgeMesh swarms working on someone else's project (e.g. ORBIS on AnyPS5) are independent and never claim endorsement. They follow upstream's contribution rules, including its AI disclosure requirements, and never send unsolicited bulk PRs upstream: only maintainer-selected, validated changes are proposed, one at a time.
