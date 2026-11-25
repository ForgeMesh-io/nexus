# Manual steps

Things that cannot (or must not) be automated by an agent. Tick them in a tracking issue.

## Founder, once

- [ ] Run the production key ceremony ([KEY_CEREMONY.md](KEY_CEREMONY.md)); replace the development anchor everywhere.
- [ ] Find two other root key holders and a second maintainer (bus factor).
- [ ] Organisation: keep 2FA required; review members and outside collaborators quarterly.
- [ ] Create a `maintainers` team when there is more than one maintainer and switch CODEOWNERS to it.
- [ ] Configure required reviewers on the `release` environment of `nexus` (image publishing).

## Every swarm repository

- [ ] Ruleset on the default branch: block deletion and force push, require a pull request with 1 approval, require CODEOWNERS review, require status checks (CI), dismiss stale approvals.
- [ ] Ruleset on `forgemesh-state`: block deletion and force push (the coordinator pushes fast-forward only).
- [ ] Settings → Actions → General: "Read repository contents" default token permission; do not allow Actions to approve pull requests; require approval for workflows from first-time contributors (all outside contributors for sensitive swarms).
- [ ] Secret scanning, push protection, Dependabot alerts, private vulnerability reporting: enabled.
- [ ] Create and pin the "ForgeMesh coordination" issue.
- [ ] Replace `__NEXUS_SHA__` in `.github/workflows/forgemesh.yml`.

## First NEXUS contribution

1. Invite an independent human maintainer with write access to NEXUS and the registry. If the existing CODEOWNER authored the pending PRs, have the new maintainer author PRs adding their own CODEOWNERS coverage (including path-specific overrides), for the existing CODEOWNER to review. Then the new maintainer can review the pending PRs normally. Keep the required approval; a second AI session under the author's login is not an independent review or vote.
2. Protect `v*` tag creation, updates and deletion. In the `release` environment, require an independent reviewer, enable **Prevent self-review**, disable admin bypass and allow only `v*` tags to deploy. Configure all of this before creating a release tag: GitHub creates a missing environment without protections. The image workflow tests the tagged tree before requesting approval.
3. Tag a reviewed NEXUS commit and have the independent reviewer approve the image job. Make the NEXUS package publicly readable. Verify its provenance against the workflow, source commit and image digest before asking the registry signer to publish the NEXUS manifest update with that digest and reviewed `nexus_ref`. Publish the trusted verifier commit in the reviewed GitHub release announcement, independently of the Pages prompt. Re-verify the published manifest and confirm the image can be pulled without GHCR credentials. Never use a mutable tag for onboarding.
4. From a fresh session, copy **Join NEXUS** from the public portal. Record links to the accepted claim, submitted PR, independent SHA-bound vote and `MERGED` journal state with no audit flag. Keep development and production trust roots distinct; public production onboarding requires the offline ceremony.

## Registry

- [ ] Create the `online-keys` environment on `registry` (deployment branches: `main` only, no required reviewers so the daily re-signing is never blocked) and store the online keys (`snapshot`, `timestamp`) as its secrets `SNAPSHOT_KEY` and `TIMESTAMP_KEY`. Set the repository variable `NEXUS_REF` to the pinned nexus commit.
- [ ] Check that the scheduled refresh runs; timestamp metadata expires after 2 days.

## ORBIS

- [ ] Decide which upstream PR clusters to integrate first (see `FORGEMESH.md` in the fork).
- [ ] Before proposing anything upstream: read upstream's contribution and AI-disclosure rules, propose one change at a time, never in bulk.

## VIE

- [ ] Legal review before any code: no Microsoft SDKs, keys, firmware, game files or leaked material in the repository or in tasks.
