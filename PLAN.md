# Plan

1. **NEXUS core** — state machine, journal with compare-and-swap, coordinator, scheduler, sandbox, attestations, TUF registry client and tooling, tests including a concurrency simulation.
2. **Workflows** — reusable coordinator, CI, image build with provenance, Pages deployment of the registry.
3. **Registry and portal** — development TUF repository, signed manifests for NEXUS, VIE and ORBIS, static portal with copyable prompts.
4. **Swarms** — NEXUS tasks; VIE research repository built from the existing-projects audit; ORBIS fork overlay with upstream sync and triage tasks.
5. **Documentation** — protocol, security, threat model, governance, procedures.
6. **Deployment** — repositories, settings, rulesets, Pages.
7. **Next** — production key ceremony (human), first external participants, scale tests.

Status of each step: [PROGRESS.md](PROGRESS.md).
