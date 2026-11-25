# NEXUS Contribution Pilot Implementation Plan

> **For agentic workers:** Execute the checklist in order. Local test identities are fixtures, never GitHub users or reviews.

**Goal:** Make it possible to hand off NEXUS improvements through the public participation prompt and prove the first contribution end to end.

**Architecture:** Keep the running Python/TUF bootstrap and GitHub journal. Verify the handoff with the existing simulator and reserve live approval, signing and release for humans.

**Tech Stack:** Python, pytest, Git, GitHub Actions, GHCR, TUF.

**Spec:** [`JOIN.md`](../../../JOIN.md), [`PROTOCOL.md`](../../../PROTOCOL.md), and [`GOVERNANCE.md`](../../../GOVERNANCE.md).

## Global constraints

- GitHub free plan; immutable pins, sandbox only for untrusted code, independent SHA-bound votes, and human review and merge. Keep existing branch rules and signer custody.
- NEXUS only. Do not make Rust, OpenSSH, VIE or ORBIS prerequisites for the pilot.

## Review focus

- A contributor cannot validate their own PR, even when a validation queue exists.
- A validator is directed to available evidence work even when the default split favours development.
- A merge is credited only after the exact recorded SHA reaches `READY_TO_MERGE`; a simulated merge is never published as pilot evidence.
- Failed tests on a release tag must prevent image publication.
- A successful registry check with an empty image map must not lead to executing with an unsigned substitute.

## Pilot slice

- [x] In `tests/test_concurrency.py`, exercise `Coordinator.run` and `scheduler.recommend` across claim, submit, an ineligible recommendation for the author, validation for the second participant, and an audit-free merge recorded on a real bare Git remote. Use the existing fake inbox. Confirm the author is rejected and the independent recommendation is actionable even when the normal split favours development.
- [x] In `forgemesh/scheduler.py`, fall back to validation when it is actionable and development is not. Fall back to development when the participant has nothing eligible to validate. Keep the existing split when both are actionable. Run the focused test and the full Python suite.
- [x] In `.github/workflows/ci.yml` and `images.yml`, reuse the same CI on the selected version tag before any publication job. Keep the existing human release gate. Lint both workflows.
- [x] In `JOIN.md` and `docs/MANUAL_STEPS.md`, make the official image check, actionable recommendation and first public handoff explicit. Verify the live entry point read-only. Leave the reviewed release tag, public attested digest, signed manifest, and independent GitHub review to their human owners.
- [ ] After human review and deployment, start a fresh session from the live prompt. Record links to the accepted claim, independent evidence, and audit-free merge before calling the full handoff proven.

## Actionable work slice

- [x] In `tests/test_scheduler_sandbox_config.py`, cover a submission waiting only for maintainer approval, a trusted vote that is still missing, a paused swarm, and a participant with no claim slot. In the real-Git rehearsal, call `next` from the persisted journal and check that the same PR is offered at the new SHA after a push; an old SHA vote must not count.
- [x] Share the existing exact-SHA readiness calculation with `scheduler.recommend` so only useful validation contributes to back-pressure. Hide new claim recommendations when the current policy would reject them. Preserve existing `next` lists and expose PR, head SHA, and missing protocol evidence on each validation task. No new GitHub requests, journal events, or merge rules.
- [x] Document that `next` reads a snapshot: check the live PR head before testing and before voting, and check required CI and review separately on GitHub. Verify with the focused tests and full suite.

## Pilot measurement

Run comparable, narrowly scoped tasks with GitHub issues, PRs, CI, and the same review rules in both groups. Add NEXUS reservations and recommendations in only one group. Leave PRs and evidence public; record reviewer minutes privately as aggregate time, not per-person telemetry. Compare redundant PRs per outcome, time from work availability to a complete exact-SHA review packet, maintainer minutes per accepted merge, and regressions over the same follow-up period. Record blocked and unfinished outcomes too. Keep the extra coordination only if it saves maintainer time without worse evidence or regression rates. A local rehearsal checks correctness; it does not measure savings.

## Self-improvement without an execution image

- [x] In `tests/test_scheduler_sandbox_config.py`, use `next --no-execution` with a local journal containing documentation work, a submitted read-only task, and tasks that need execution or hardware. Verify eligible claims and the exact-SHA validation target remain; execution-required tasks are excluded even when their mode is omitted, and capability detection is not called.
- [x] In `forgemesh/__main__.py` and `forgemesh/scheduler.py`, make that flag filter both lists. Do not let it change claim policy or `READY_TO_MERGE`. Keep default recommendations compatible.
- [x] Set `NX-0006` to a text-only improvement of `JOIN.md`. Give its independent reviewer acceptance checks that do not execute PR files, and keep GitHub required CI. Document the handoff and give newcomers a GitHub issue template for actionable feedback that does not duplicate existing work.
- [x] Verify the first task and a handoff on a real local Git journal. Do not count the bootstrap push as a swarm contribution.
- [ ] Record the first real public submission, independent validation, and human integration.
