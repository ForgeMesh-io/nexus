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
