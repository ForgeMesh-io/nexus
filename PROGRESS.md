# Progress

Updated: 2026-11-25. Only facts that were checked are listed. Test counts come from local runs.

## Done

| Item | Evidence |
|---|---|
| Core state machine, journal with Git compare-and-swap, coordinator, scheduler | `tests/` — 90 tests passing locally (Python 3.12) |
| Concurrency simulation: 40 agents, 8 concurrent coordinators, 5 tasks, real Git remote | `tests/test_concurrency.py`, 3 random seeds, no double claim |
| TUF registry (development keys), verifying client, end-to-end over HTTP | `tests/test_registry.py`, `tests/test_e2e_verify.py` |
| Sandbox | Test suite run inside it: uid 1000, network blocked, read-only root (manual check) |
| Images `base`, `nexus`, `vie`, `orbis` | Built locally; toolchains and lavapipe Vulkan checked. Not yet published to GHCR |
| Workflows | `actionlint` 1.7.7 + shellcheck clean. On GitHub (2026-11-25): `ci` passes on `nexus`; registry `pages` re-signs, self-verifies and deploys; the VIE coordinator answered `/fm claim` and `/fm release` in issue #1 and wrote its journal to `forgemesh-state` |
| Deployment | Repositories `nexus`, `registry`, `vie`, `anyps5` (fork, default branch `forgemesh`) with rulesets, pinned coordination issues, read-only default token, secret scanning and push protection |
| Swarm configurations | NEXUS 8 tasks, VIE 12 tasks, ORBIS 14 tasks; `forgemesh check-config` passes |

## Not done / not verified

- Production key ceremony (needs humans, offline). The registry uses development keys.
- `images.yml` has not run yet (needs a `v*` tag and the `release` environment); manifests have no image digests until then.
- Portal statistics are filled by the next `pages` run after a swarm has a `forgemesh-state` branch.
- No real participant has used the protocol yet.
- Scale beyond the simulation (hundreds of agents, GitHub API quotas) is not measured (NX-0005).
- Windows capability detection (NX-0008).
