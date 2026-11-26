# ADR 004: Patches are checked in a sandbox and posted as comments, not opened as pull requests

**Status:** Accepted for the pilot. **Date:** 2026-11-26.

## Problem

Text reports can only describe a fix. Many real needs, such as a wrong build step in a document, are cheaper for a maintainer to accept as a ready change. A code artifact brings three new risks:

- it can reach files outside what the project agreed to;
- it can carry content that is dangerous to apply (symlinks, modes, `.git`);
- opening pull requests multiplies the review load and needs write access to Git.

## Options

| Option | GitHub permission | Reason |
| --- | --- | --- |
| Text reports only | Issues write | Safe, but leaves the maintainer to write every fix. |
| **Unified diff, checked, posted on the issue** | Issues write (unchanged) | **Chosen.** No new permission. One more comment through the same exclusive gateway, quota and reconciliation. The maintainer applies it with `git apply` or ignores it. |
| Coordinator opens pull requests | Contents write + Pull requests write | Rejected for now. [Contents write is repository-wide](https://docs.github.com/en/rest/authentication/permissions-required-for-github-apps): it can push to any unprotected branch. [Creating a pull request](https://docs.github.com/en/rest/pulls/pulls#create-a-pull-request) "triggers notifications" and needs "write access to the head or the source branch". A pull request also starts the project's CI on untrusted code. Reconsider once a project asks for it and its branch protection is verified. |
| Contributors open their own pull requests | None for Nexus | Outside Nexus's bounds: no quota, no deduplication. This is what Nexus exists to prevent. |

## Decision

- **Task kind.** A task has `kind` `report` (default) or `patch`. A patch task must list `paths`: they are both the files it may read and its write scope.
- **Submission.** A patch is submitted like a report, but may be up to 16 KiB instead of 8 KiB. The ledger never runs it.
- **Check before review.** `nexus-pilot DB check-patch {"task", "repository"}` (operator-only) checks the patch against an operator-owned local clone containing the pinned base. Every Git step runs in [Bubblewrap](https://github.com/containers/bubblewrap) with:
  - no network, a cleared environment, no home directory and a private `/tmp`;
  - the clone mounted read-only.

  It extracts the exact pinned tree with `git archive`, **without `.git`**, then runs `git apply --numstat` and `git apply --check`. It refuses:
  - with `forbidden_change`: mode changes, symlinks, submodules, renames, copies, binaries, `.git` paths, or paths that leave the tree;
  - with `out_of_scope`: any file outside the task's paths;
  - with `does_not_apply`: a patch that does not apply cleanly at the base.

  `git apply` already rejects paths outside the working area by default ([documentation](https://git-scm.com/docs/git-apply): "rejected as a mistake (or a mischief)"). The sandbox and the `.git`-free tree are a second layer.
- **Failed check.** A failed check is a final rejection, with no reviewer. It releases the admission slot (ADR 002 rule).
- **Review and publication.**
  - Reviewers only see checked patches, together with the list of files.
  - `review` before a check returns `not_checked`.
  - The publisher refuses an unchecked patch.
  - It also re-reads the consent file. Every changed file must be covered by its optional `patch` list. Without `patch`, the project accepts no patches.
- **Posting.** The comment is an indented code block, so the diff cannot close a fence or inject markup. It names the base commit and the SHA-256 of the patch.

The pilot never executes the patched code: no build, no tests. A patch can be *well-formed and in scope*, yet still wrong. Judging that remains the reviewer's job.

**Quotas and deduplication** stay the existing ones:
- one task per issue;
- one publication per task, with a unique marker and reconciliation by body, marker and bot ID;
- `publication_limit` per ledger, and one ledger per repository.

These now apply to patches with no new mechanism.

## Not decided here

- **Running tests on a patched tree.** This needs a pinned toolchain image per project. It also needs CPU, memory and time limits, and an output size bound. `forgemesh/sandbox.py` (Docker, digest-pinned image, `--network none`) has those parts, but no project has declared a test command yet. Defer until one does: the declaration belongs in the consent file.
- **Semantic conflicts between two patches on the same file.** One task per issue and the stale-base rule (ADR 002) limit them. They do not detect them.
- **gVisor or a microVM.** Bubblewrap only isolates trusted Git reading untrusted input. Nothing untrusted is executed, so a stronger boundary is not yet justified.

## Consequences

- The operator needs `bwrap` and a local clone for patch tasks. Without them, `check-patch` returns `sandbox_unavailable` or `base_unavailable`, and the patch waits. This is the safe degraded mode.
- Projects opt in to patches separately and per path (`"patch": ["docs/"]`).
