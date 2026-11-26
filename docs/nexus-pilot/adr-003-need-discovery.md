# ADR 003: Propose tasks from consented issues; the maintainer selects

**Status:** Accepted for the pilot. **Date:** 2026-11-26.

## Problem

The operator had to find issues and type each `add-task` by hand. Nexus had no view of what the project actually needs. It also could not tell whether a human was already working on an issue, so it could duplicate or overrun that work.

## Options

| Option | Reason |
| --- | --- |
| Agents pick any open issue | Rejected. Vague issues produce plausible but unvetted output (NotebookLM: *Specs In, Software Out*). Human ownership signals would be ignored. Consent would not be scoped. |
| Rank by labels (`help wanted`, `good first issue`) | Not the source of truth. Labels can be set by triagers without write access (ADR 002), and practice varies between projects. They are shown to the maintainer as context but filter nothing. |
| Reproducible CI failures | Strongest signal per the notebook. But it needs workflow-log access (`actions:read`) and a reproduction sandbox. Deferred until a patch artifact exists: a report about a red build adds little. |
| **Issues listed in `.github/nexus.json`, filtered for human work** | **Chosen.** The maintainer already named these issues as consented. Nexus only removes those it should not touch, and the maintainer picks. |

## Decision

`nexus-pilot DB propose` (operator-only, read-only) reads the default-branch head and the consent file at that commit. It then examines at most 15 listed issues in file order and **skips** any that:

- is already a ledger task;
- is unavailable, a pull request, closed or locked;
- has an assignee;
- has an open pull request cross-referencing it in the [timeline](https://docs.github.com/en/rest/using-the-rest-api/issue-event-types) (`source.issue.pull_request` present, `state` open);
- has a net-positive `connected` / `disconnected` balance, meaning a manually linked PR;
- has more than 200 timeline events: unbounded history is skipped, not guessed.

Each remaining issue is returned with its labels, comment count and last update. It comes with a ready `add_task` object: id `issue-N`, the current head as `base`, a title cut to 256 bytes, and `paths` set to the consent file's `read` list.

Nothing is written. The maintainer chooses which proposals to pipe into `add-task`, and may narrow `paths`.

- Reads are anonymous by default. A run makes at most 3 + 15 × 3 = 48 requests, under GitHub's 60 unauthenticated requests per hour.
- `NEXUS_GITHUB_TOKEN`, if set, is used only to raise that limit. It is never printed.

## Not decided here

- **Recent human comments** are not treated as a claim. A comment like "I'll take this" is free text, and parsing it is exactly the kind of non-binding signal the notebook warns about. The maintainer sees `comments` and `updated_at` and decides.
- **Ranking**: candidates keep the maintainer's own order in the consent file. No score is invented.
- **Freshness after selection**: a human may self-assign after the proposal. The publisher re-checks consent but not assignees. Adding that check is cheap. Defer it until a live run shows that the race happens.
- **Linked branches**: the `development` panel is GraphQL-only. Not read.

## Consequences

- The maintainer's job becomes: list issues once in the consent file, run `propose`, pick. Removing an issue from the file removes it from both proposal and publication.
- One proposal run costs ≤ 48 GitHub reads and no writes.
