# Adding a swarm

A swarm is one GitHub repository plus a delegated role in the registry.

## 1. Proposal

Open an issue on `ForgeMesh-io/registry` with: name (lowercase), codename (uppercase), objective, repository, licence, legal review (no proprietary SDKs, keys, game data or copyrighted assets), maintainers, and what hardware participants need.

The founder decides. Reasons to refuse: legal risk, no maintainer, no clear objective, duplication of an existing swarm.

## 2. Repository

1. Create the repository in `ForgeMesh-io` (or fork the upstream project there).
2. Copy from `nexus/templates/swarm/`: `.github/workflows/forgemesh.yml` (replace `__NEXUS_SHA__`), `AGENTS.md`, `CODEOWNERS`, PR template.
3. Write `.forgemesh/policy.json` and the first tasks; check with `python -m forgemesh check-config .`.
4. Apply the repository settings in [MANUAL_STEPS.md](MANUAL_STEPS.md) → "Every swarm repository".
5. Create the coordination issue ("ForgeMesh coordination"), pin it, and lock nothing: comments are the inbox.

## 3. Registry

1. The swarm key holder generates the swarm key (public part only shared).
2. The founder delegates `swarms/<name>/*` to it (`Repo.delegate_swarm`), signing `targets` offline.
3. The swarm key holder signs `swarms/<name>/manifest.json` (schema: `forgemesh/schemas/manifest.schema.json`).
4. Add the swarm to `registry/swarms.json`; the portal shows a card automatically.

## 4. Removing a swarm

Set the manifest `status` to `revoked` and republish, then `Repo.revoke_swarm`. Clients refuse it at their next refresh.
