# Roadmap

## Phase 1 — NEXUS alpha (current)

- [x] Event-sourced coordination on a Git branch with compare-and-swap
- [x] Leases, dependencies, WIP limits, risk-based independent validation
- [x] Reusable coordinator workflow, CI, image build with provenance
- [x] TUF registry with development keys, verifying client, portal
- [x] Locked-down sandbox and test attestations
- [ ] Production key ceremony (human, offline)
- [ ] First real external participants on NEXUS tasks

## Phase 2 — Pilot swarms

- [ ] ORBIS: upstream sync, PR cluster triage, first integrated batch on the `forgemesh` branch
- [ ] VIE: keep XCL's Windows x64 baseline; demonstrate a synthetic title through a native host runtime on Linux and macOS before claiming platform support
- [ ] Dashboard JSON generated from state branches (NX-0002)

## Phase 3 — Scale

- [ ] Load test with hundreds of simulated agents (NX-0005)
- [ ] Journal compaction (snapshot + truncated journal)
- [ ] Overlap detection across submissions (NX-0007)
- [ ] Merge queue integration for low-risk categories
- [ ] Sigstore-signed test attestations

## Phase 4 — Open the registry

- [ ] Documented process for third parties to propose a swarm
- [ ] Per-swarm key holders other than the founder
