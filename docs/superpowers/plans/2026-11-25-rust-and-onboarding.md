# Rust and Project Onboarding Implementation Plan

**Goal:** Move ForgeMesh tooling to Rust without losing journal history, and let participants contribute whether or not they have a project's optional private resources.

**Architecture:** Keep the public GitHub journal and its deterministic replay. Treat resource availability as a local scheduling input, not a public participant record. Build the portal from public evidence and verify the registry before relying on project instructions.

**Constraints:** GitHub only; no mandatory service or client. Never upload private resources or automate their access. Do not activate a migration until tests pass and the maintainer reviews it.

## 1. Read-only Rust tooling and resource onboarding

- [x] Pin compatibility with existing journal decisions and state, including expiry, SHA-bound validation and independent votes. Keep the existing JSON schemas and CLI output contract.
- [x] Add a Rust `forgemesh resources [ROOT]` command for the optional, protected `.forgemesh/resources.json` map of resource IDs to plain questions. `check-config` rejects undeclared `resource:<id>` task requirements. `next --resource <id>` is local, repeatable and opt-in. Test no-resource recommendations, mixed hardware/resource requirements, and validation fallback.
- [x] Use the existing `hardware` capability list for task requirements so older coordinators can still read new definitions. Document the verification → resource questions → recommendation sequence. Mark only VIE tasks that actually require a private resource; retain independent source, algorithm and synthetic-fixture work. Never automate device access or artifact intake.

## 2. Coordinator and build migration

- [x] Port comment parsing, GitHub ingestion, append-only non-force Git publication, sandboxing and attestations. Exercise real Git contention with the existing 40-agent/eight-writer scenario before switching any caller.
- [x] Provide Cargo `fast` and portable `release` profiles; document native CPU tuning and measured PGO as optional. Document matching CMake modes in the ORBIS overlay without modifying upstream build files.
- [ ] After review, enable the opt-in Rust workflow on one swarm and check the first run. Publish and attest images only after maintainer approval. Keep immutable pins.

## 3. Signed registry and static portal

- [x] Add a two-distinct-signers OpenSSH verification path using independently pinned public keys before repository code runs. Test tampering, expiry, wrong repository/swarm and repeated signatures.
- [ ] Complete the offline signing ceremony and publish the pinned signer list before changing the active registry path. Keep TUF live until then.
- [x] Use public journal/state only for project progress, the GitHub-login leaderboard and impact views. Test empty/unavailable swarms and attribution that cannot be inflated by repeated claims. Add the short English prompt and banner; verify keyboard use and failure states.
