# Nexus pilot: mission and release gates

Nexus lets people offer help from their own AI client to a project that explicitly opts in. The project keeps its workflow and authority. A copy-paste instruction is an entry point, not a grant of tools, credentials, or permission to publish. Where a client cannot connect, it can help draft locally; it must not claim to have joined, reserved, or validated anything.

## First vertical slice

One public repository per install. A maintainer selects a real need, an existing issue and a full base commit. A volunteer can discover and reserve it, then submit a bounded text report on that revision. A separately enrolled reviewer can examine the exact report and record evidence; a maintainer chooses whether to authorize its publication. The only planned external mutation in this slice is one comment on the chosen existing issue, through a separate publisher. The coordinator never executes submitted content. Code changes, new issues, and opening PRs are later slices, not implied by the text pilot.

1. Local proof: authenticated roles, bounded discovery/admission, exclusive expiring leases, fenced submits, provenance and independent review; audited stop, revocation and crash/retry behavior.
2. Publication proof: separate principal, atomic quota and durable dispatch intent, fail-closed reconciliation, no duplicate send on uncertainty, and an opt-in test on an authorized fixture repository. No automatic merge.
3. Usability proof: clean install and removal, no changes outside Nexus opt-in and activity, OpenCode plus another actual client, and a documented safe manual fallback.
4. Value proof: record common-budget comparisons against single and independent agents. Do not promote a pilot on throughput alone or test counts alone.

Tag evidence as **local observed**, **simulated**, **live observed**, or **not run**. Release requires a reproducible acceptance audit, including controller/credential isolation, publish/reconcile, revocation, operator recovery and maintainer feedback. Public release and any change in GitHub access require the appropriate authorization. Preserve the existing Apache-2.0 license and operational path; neither a change of license nor a repository deletion is part of the pilot.
