# ADR 002: Repository-declared consent, checked by the publisher

**Status:** Accepted for the pilot. **Date:** 2026-11-26.

## Problem

Until now, the operator's ledger alone decided that a project had opted in. The GitHub App installation shows that someone with admin rights accepted the App, but it grants Issues write on the whole repository. It cannot say which issues Nexus may answer or which files agents may rely on. Nothing in the project itself recorded consent, so a maintainer could not withdraw it without access to the operator's host.

## Options

| Option | Who can change it ([GitHub roles](https://docs.github.com/en/organizations/managing-user-access-to-your-organizations-repositories/managing-repository-roles/repository-roles-for-an-organization)) | Reason |
| --- | --- | --- |
| App installation scope only | Organization or repository admin | Grants repository-wide permissions with no per-issue or per-path scope. Necessary, not sufficient. |
| Issue label such as `nexus:ok` | Triage and above ("Apply/dismiss labels") | Too weak for consent. Triage is meant for people working "without write access", and labels have no history in Git. Possible later as a *need signal*, not as consent. |
| **File on the default branch** | Write and above ("Push to"), subject to the project's branch protection and CODEOWNERS | **Chosen.** It is the Dependabot / Renovate pattern: versioned, reviewable, and governed by the project's own rules. Deleting the file withdraws consent. |
| Reuse the legacy `.forgemesh/policy.json` | Same as a file | Rejected. It describes the earlier swarm workflow: votes, risk levels, validation pressure. Requiring it would impose that organization on projects. |

## Decision

A project consents by committing `.github/nexus.json` to its default branch:

```json
{"nexus": 1, "issues": [1], "read": ["CONTRIBUTING.md", "docs/dev/"]}
```

- `issues`: the only issues Nexus may comment on.
- `read`: the files, or directories ending in `/`, that a task may rely on.
- Unknown keys, versions other than `1` and malformed paths are rejected (`invalid_consent`). Rejecting unknown keys avoids a silent difference between what the maintainer believes they configured and what Nexus enforces.

The publisher re-reads the file **at the exact default-branch commit it is about to publish against**, after maintainer authorization and before the single send grant. It refuses with `no_consent` if:

- the file is absent,
- the issue is not listed,
- or a path the task relies on is not covered.

A refusal makes no write and consumes no grant. Restoring the file lets the same authorization proceed once.

Each task now records the paths it relies on (`add-task` field `paths`, at most 16). They are shown to contributors in `discover`, so the harness knows what it may read. The stale-base rule is relaxed:

- If the default branch moved, the publisher fetches [`compare/{base}...{head}`](https://docs.github.com/en/rest/commits/commits#compare-two-commits).
- The report stays current only if the status is `ahead`, the response is complete (fewer than 250 commits and fewer than 300 files, GitHub's documented truncation points), and no changed or renamed file falls in the task's paths.
- Changes to the consent file itself are ignored, because it is re-checked separately.
- A task without paths tolerates no other change.
- The audit records the commit checked (`dispatch_started.head`).

Without this rule, every unrelated commit would invalidate a review, and the first commit adding the consent file would make every pending report stale.

## Not decided here

- Consent is checked at publication only. Agents can still read a repository that later withdraws consent. The project's files are public, and nothing is written until the check passes.
- Moving consent to intake (`add-task`) needs a GitHub read in the operator path. Defer this until there is an automatic need-discovery step that reads the repository anyway.
- Per-path *write* scope needs a patch/PR artifact. There is none in the pilot. App `contents:write` would be repository-wide, so it would have to be enforced by the publisher, as is done here for comments.
- `.github/nexus.json` is protected only as far as the project protects its default branch. A user with write access can grant consent. That matches who can already merge code.

## Consequences

- Maintainers can withdraw consent without contacting the operator. They delete the file or remove an issue, and the next publication refuses.
- Existing ledgers need `nexus-pilot DB upgrade`. Tasks created earlier get `paths: []`, the strict rule.
- One extra read request per publication, plus one compare request when the branch moved.
