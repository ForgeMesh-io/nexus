# Nexus release roadmap and progress

**2026-11-27: approximately 70% toward the first installable release (65–75%).** This is an evidence-weighted planning estimate, not a calendar forecast or a percentage of the universal vision. Missing acceptance gates still block release. See the [mission](mission.md) and [evidence](evidence.md).

| Release area | Weight | Credit | Evidence and next gate |
| --- | ---: | ---: | --- |
| Coordination and limits | 30 | 28 | SQLite leases, role checks, bounded intake, independent review, quota, audit, and local contention/retry checks exist. The clean-install synthetic restore preserved audit, revocation and stop. No live ambiguous-send recovery. |
| Project opt-in and useful work | 15 | 12 | Real fork consent exists; proposal and preflight checks are bounded. A real agent submitted a report; a patch passed the mechanical check and was rejected on substance. Get maintainer feedback on usefulness and document what signals can be missed. |
| Live GitHub delivery | 20 | 19 | Fork-only App installation verified. One approved report published and independently verified, then reconciled with the same receipt; stale digest refused, pilot stopped and credentials revoked. No live recovery from an ambiguous POST. |
| Installation and onboarding | 25 | 10 | A verified Linux x86-64 wheelhouse installs offline without cache; host-policy checks and an operator-driven Antigravity model run exist. Next: observe a non-technical volunteer connect, submit and detach without coaching; distinguish a prepared connector from self-installation. Test the safe fallback separately. |
| Comparative value and release decision | 10 | 1 | Frozen tasks, limits, and a blind rubric exist; scripted dispatch is verified. OpenCode `steps` does not enforce the ceilings. The local synthetic solo run stopped with known usage, but that does not qualify the scored setup. Qualify the runner and secure consent before recording scored quality, resources, or human time. No declared winner or release yet. |
| **Total** | **100** | **70** | |

## Next in order

1. **Make the alpha usable without an operator typing the participant's answers.** Use the [clean installation and withdrawal checklist](rehearsals/clean-install.md) to observe a consenting volunteer independently complete the participant steps. Do not make an internet-facing service a prerequisite for testing a supported local harness.
2. **Measure whether coordination is worth it.** Use the [frozen three-arm protocol](rehearsals/three-arm.md). A zero-output arm stays in the results. Report simulation, load tests, and real use separately. Avoid changes to agent count or admission based on an unmeasured productivity claim.

## Architecture review (2026-11-27)

The [project notebook](https://notebooklm.google.com/notebook/63eaa524-b0ed-4e6a-b5fb-983400940e82) now exposes the indexed Rust roadmap (§§1, 3; source `669c5f4c-1b27-4543-a222-998455c734a5`), Nexus architecture (source `fc3c1dbc-8d17-49ba-9f88-0222f119c773`) and SwarmOS architecture (source `72a508cf-3726-4b5e-92af-3067ee14b72e`). This review used their text, not a reconstruction or the original Studio artifact. Treat architecture proposals and cited performance claims as hypotheses until checked against primary sources and this pilot.

| Proposal | Decision for the first release | Evidence or trigger to revisit |
| --- | --- | --- |
| Keep draft work off GitHub, throttle intake when review is full, and reserve the integration decision for humans. | Keep. A submitted report holds an admission slot pending review or a maintainer decision. Only the separate publisher can send an approved comment. | [Pilot acceptance](evidence.md#what-the-evidence-covers); no evidence yet that the gate saves reviewer time. |
| Put onboarding before infrastructure scale; use an open tool interface. | Keep local MCP and the manual draft fallback. Deliver credentials outside the prompt. | An authenticated `discover` is the connection check; catalogue presence alone is not. Require unassisted observation before broadening client support. |
| Rewrite the coordinator in Rust and use Git/CRDT replication, distributed messaging and AST-based coordination. | Defer. The single local SQLite authority supplies the hard quota and transaction boundary already exercised. Convergent history alone does not enforce a unique dispatch. | [ADR 001](adr-001-coordination.md). Revisit on measured write contention, recovery burden or an approved multi-host requirement. No change to the existing Rust worktree or GitHub-native workflow. |
| Automatically score net contribution value before involving maintainers. | Do not ship a proxy score. First measure usefulness, review burden and total human effort at matched budgets, including refusals and zero-output sessions. | [Comparison protocol](rehearsals/three-arm.md); no scored runs yet. |

## Later, only with evidence

- **Optional contribution allowance:** let a volunteer choose how much time or subscription usage to donate to a project. Start with capabilities the harness actually offers; a prompt or self-report is advisory and cannot enforce provider spend. Retain separate atomic project quotas for review and publication. No billing service or mandatory paid budget in the pilot.
- **Semantic discovery and stronger validation:** try one specific signal against the current baseline and measure false positives, missed human work, and reviewer minutes. For patches, a scope check is not functional validation; require a separately authorized, isolated validation path before executing code.
- **Broader interoperability and scale:** add remote authentication, further protocols, distributed scheduling, or richer forge automation only when a supported use case and measured bottleneck justify them. The indexed architecture's proposed AST/CRDT substrate, very large agent pools, NATS, and merge queues are hypotheses, not release prerequisites. Keep the maintainer's ability to pause and detach independent of these experiments.
