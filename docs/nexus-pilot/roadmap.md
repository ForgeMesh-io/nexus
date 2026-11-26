# Nexus release roadmap and progress

**2026-11-26: approximately 60% toward the first installable release (55–65%).** This is an evidence-weighted planning estimate, not a calendar forecast or a percentage of the universal vision. Missing acceptance gates still block release. The original NotebookLM Studio report was not accessible; the longer-term themes below come from its indexed sources and are not a transcription. See the [mission](mission.md), [evidence](evidence.md), and [research](research.md#round-6--2026-11-26-what-to-ship-before-scaling).

| Release area | Weight | Credit | Evidence and next gate |
| --- | ---: | ---: | --- |
| Coordination and limits | 30 | 28 | SQLite leases, role checks, bounded intake, independent review, quota, audit, and local contention/retry checks exist. Rehearse operational recovery and isolation on a clean install. |
| Project opt-in and useful work | 15 | 12 | Real fork consent exists; proposal and preflight checks are bounded. A real agent submitted a report; a patch passed the mechanical check and was rejected on substance. Get maintainer feedback on usefulness and document what signals can be missed. |
| Live GitHub delivery | 20 | 9 | HTTP-double coverage and real read-only preflight. Narrow the App installation to the fork, publish one approved report, verify the bot/comment independently, reconcile without a second POST, and record refusal plus stop/revoke. |
| Installation and onboarding | 25 | 10 | Wheel, CLI, MCP bridge, Antigravity model run, and host-policy tests exist. Package a reproducible candidate and have a non-technical volunteer install, connect from a compatible harness, submit, and detach without operator prompts. Test the documented safe fallback separately. |
| Comparative value and release decision | 10 | 1 | Measurement protocol exists. Run the solo/independent/Nexus comparison with common limits and consented review, report quality, actual resources, and active human minutes. No declared winner or release yet. |
| **Total** | **100** | **60** | |

## Next in order

1. **Finish the live gate.** Keep the single-fork, single-issue, one-comment scope. Follow the [acceptance record](evidence.md#live-gate); do not mint a publisher token under an all-repositories installation. Keep unvalidated or withdrawn material out of GitHub.
2. **Make the alpha usable without an operator typing the participant's answers.** Document a clean installation and connection, then observe a fresh volunteer complete it. Record human steps, time, blockers, denied capabilities, and successful removal. Do not make an internet-facing service a prerequisite for testing a supported local harness.
3. **Measure whether coordination is worth it.** Use the [three-arm protocol](research.md#three-arm-experiment-not-run). A zero-output arm stays in the results. Report simulation, load tests, and real use separately. Avoid changes to agent count or admission based on an unmeasured productivity claim.

## Later, only with evidence

- **Optional contribution allowance:** let a volunteer choose how much time or subscription usage to donate to a project. Start with capabilities the harness actually offers; a prompt or self-report is advisory and cannot enforce provider spend. Retain separate atomic project quotas for review and publication. No billing service or mandatory paid budget in the pilot.
- **Semantic discovery and stronger validation:** try one specific signal against the current baseline and measure false positives, missed human work, and reviewer minutes. For patches, a scope check is not functional validation; require a separately authorized, isolated validation path before executing code.
- **Broader interoperability and scale:** add remote authentication, further protocols, distributed scheduling, or richer forge automation only when a supported use case and measured bottleneck justify them. The indexed architecture's proposed AST/CRDT substrate, very large agent pools, NATS, and merge queues are hypotheses, not release prerequisites. Keep the maintainer's ability to pause and detach independent of these experiments.
