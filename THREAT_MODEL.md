# Threat model

## Assets

1. Participants' machines, credentials (GitHub token, AI API keys, SSH keys) and personal data.
2. Integrity of each swarm's main branch and released artifacts.
3. The registry trust root and swarm identities.
4. Fairness and liveness of task allocation.
5. Maintainers' time.

## Adversaries

| Adversary | Capabilities |
|---|---|
| Malicious contributor | Many GitHub accounts, arbitrary PRs/comments, prompt injection, can run their own coordinator code locally |
| Malicious or confused agent | Follows injected instructions, fabricates results, claims tasks and vanishes |
| Compromised upstream project | Pushes malicious code that ORBIS syncs |
| Impersonator | Clones the portal, publishes a fake registry and prompt |
| Compromised maintainer account | Holds write access to one repository |
| GitHub outage / Actions failure | Cancelled, delayed or duplicated workflow runs |

## Threats and mitigations

| # | Threat | Mitigation | Test |
|---|---|---|---|
| T1 | Two participants obtain the same exclusive task | Journal + Git non-fast-forward compare-and-swap, deterministic fold | `test_concurrency.py::test_many_agents_race_for_few_tasks` |
| T2 | Agent disappears holding a task | Leases with expiry, bounded renewals, scheduled reconciliation | `test_vanished_agent_does_not_block_forever`, `test_lease_expiry_redistributes_through_coordinator` |
| T3 | Replayed / duplicated events | Event ids, idempotent fold | `test_replayed_event_is_ignored`, `test_replayed_runs_are_idempotent` |
| T4 | Workflow run cancelled mid-way | Nothing is published before the push; next run re-reads comments | `test_interrupted_run_is_recovered_by_next_run` |
| T5 | Author validates own work | Author/claimant votes rejected | `test_author_cannot_validate_own_contribution` |
| T6 | Sybil validators (many accounts) | Trusted validators required from `high` risk; maintainer approval; audits of merged work | `test_high_risk_needs_trusted_vote_and_maintainer_approval` |
| T7 | Patch weakens the tests that judge it | Protected paths → maintainer approval in ForgeMesh **and** CODEOWNERS review in GitHub | `test_protected_path_change_requires_maintainer`, `test_submission_flow_with_pr_and_prompt_injection` |
| T8 | Vote for one commit, merge of another | Votes bound to head SHA; new push resets votes; merge SHA checked and audited | `test_new_push_invalidates_votes`, `test_merge_without_validation_is_flagged_for_audit` |
| T9 | Prompt injection in issues/PRs | Strict command grammar, no interpolation, agent instructions treat content as data | `test_parser_is_strict`, `test_submission_flow_with_pr_and_prompt_injection` |
| T10 | Forged/tampered manifest | TUF signatures | `test_tampered_manifest_is_rejected` |
| T11 | Signature by unknown key | TUF key ids from delegations | `test_unknown_key_signature_is_rejected` |
| T12 | Expired metadata / freeze attack | TUF expiry; timestamp valid 2 days | `test_expired_metadata_is_rejected` |
| T13 | Rollback to older metadata | TUF version monotonicity | `test_rollback_to_old_metadata_is_rejected` |
| T14 | Swarm key signs for another swarm | Terminating delegations restricted to `swarms/<name>/*` | `test_swarm_cannot_sign_for_another_swarm` |
| T15 | Root key compromise (one key) | 2-of-3 threshold | `test_root_rotation_with_threshold`, `test_old_root_key_leak_cannot_forge_after_rotation` |
| T16 | Fake portal / fake registry | Anchor hash in prompt, independent check on first use, mismatch ⇒ stop | `test_wrong_anchor_stops_bootstrap` |
| T17 | Image substitution | Digest pinning in signed manifests; provenance attestations | `test_sandbox_requires_digest_pinned_image` |
| T18 | Malicious build reads secrets / exfiltrates | Sandbox: no network, no mounts of home/socket/credentials, workspace copy | `test_sandbox_defaults_are_locked_down` + manual check (network blocked, read-only root, uid 1000) |
| T19 | Resource exhaustion on participant machine | CPU/memory/PID/time limits | `test_sandbox_defaults_are_locked_down` |
| T20 | Comment flood / API quota exhaustion | 5 commands per comment, incremental `since` cursor, back-off on 403/429 | partial (`test_parser_limits_commands_per_comment`) |
| T21 | Swarm compromised | Kill switch `paused`; registry revocation | `test_kill_switch_pauses_claims`, `test_revoked_swarm_is_no_longer_trusted` |
| T22 | Agents change their own rules | Policy/workflows/tests protected; NEXUS cannot merge them without humans | configuration + `test_protected_path_change_requires_maintainer` |

## Residual risks (not solved)

- **Docker escape**: containers share the host kernel. Use `execution: isolated` (VM) for risky tasks. Native GPU tests run real code on real drivers and are therefore opt-in only.
- **Fabricated evidence**: a vote's evidence link is not verified automatically. Higher risk levels rely on trusted validators and maintainers.
- **Collusion of trusted validators** with an author is not detectable by the protocol.
- **GitHub itself** (Actions, Pages, account security) is trusted. Mandatory 2FA is enabled for the organisation.
- **Edited or deleted comments** after ingestion do not change the journal (by design); the journal is the record.
- **Coordinator token scope**: `contents: write` on the swarm repository. Protect every branch other than `forgemesh-state` with rulesets so this token cannot push to them.
- **Scale**: tested in simulation with 40 agents / 8 coordinators per run. Behaviour with thousands of participants and GitHub API quotas is not yet measured (task NX-0005).
