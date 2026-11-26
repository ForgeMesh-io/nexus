# Nexus research log

## Round 1 — 2026-11-26: choose the first experiment

Budget: one NotebookLM triangulation round and one conflicting-evidence pass on the decisions below. No model benchmark or paid inference in this round. Prefer primary sources and separate hypotheses from findings. Stop searching once another source is unlikely to change the first slice; revisit after local and live measurements.

| Primary source checked | What it supports | What it does not establish |
| --- | --- | --- |
| [Cemri et al., MAST, v3](https://arxiv.org/abs/2503.13657v3) | Failures include system design, misalignment and verification; record these separately. | A peer vote guarantees correctness. |
| [Kim et al., scaling agent systems, v3](https://arxiv.org/abs/2512.08296v3) | Coordination payoff varies across benchmarks and task structures; keep a single-agent default/fallback. | A universal agent-count rule or expected Nexus speedup. |
| [Sarkar, before the PR, v1](https://arxiv.org/html/2606.19616v1#S4) and [Grite](https://github.com/neul-labs/grite) | Record pre-PR duplicates and combine reservation with durable completion state. | The reported reductions transfer to real LLM agents: measured agents were seeded synthetic actors, and the leases are advisory. |
| [Özaytürk and Buzluca, PASC](https://doi.org/10.4230/LIPIcs.ESEM.2026.18) | Two agents sharing action observations beat silent parallel and single-agent baselines on the reported Python repair benchmark. | Sharing a live workspace with strangers is safe, or more than two agents improve outcomes. |
| [Huang et al., EvoGit, v1](https://arxiv.org/abs/2506.02049v1) | An alternative for branching experiments with a measurable fitness function. | A safe publication policy or proof of maintenance benefit for arbitrary repositories. |
| [METR early-2025 trial, v2](https://arxiv.org/abs/2507.09089v2), [METR 2026 update](https://metr.org/blog/2026-02-24-uplift-update/) and [Paradis et al., enterprise RCT, v3](https://arxiv.org/abs/2410.12944v3) | Experienced OSS developers in the early METR trial took 19% longer with AI; an internal Google trial estimated roughly 21% less time with wide uncertainty. METR's follow-up flags selection and time-reporting issues. | A contradiction on one population or a transferable estimate of net value. The tasks, tools and experimental settings differ. |
| [SQLite isolation](https://www.sqlite.org/isolation.html), [Google SRE on overload](https://sre.google/sre-book/handling-overload/), [GitHub REST best practices](https://docs.github.com/en/rest/using-the-rest-api/best-practices-for-using-the-rest-api), [GitHub App permissions](https://docs.github.com/en/apps/creating-github-apps/registering-a-github-app/choosing-permissions-for-a-github-app) | Local atomic writes, admission/backpressure and minimum remote permissions. | SQLite can make a GitHub POST atomic with its own transaction. |
| [Ostrom's prize lecture listing](https://www.nobelprize.org/prizes/economic-sciences/2009/ostrom/lecture/) | A starting point for project-level autonomy and shared governance research. | Empirical evidence about coding-agent systems; read the lecture before extending the analogy. |
| [MCP transport 2025-11-25](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports), [A2A 1.0](https://a2a-protocol.org/v1.0.0/specification) | Tool access vs remote agent discovery/delegation are separate design concerns. | A plain chat can connect, call tools, authenticate or install a server. |

The [reference notebook](https://notebooklm.google.com/notebook/63eaa524-b0ed-4e6a-b5fb-983400940e82) had 120 indexed sources before the pass. Added only the public METR update (`6aabbccc-3a9c-4328-a70a-86d73b19d1d7`), enterprise RCT (`d4ca9d47-99e9-4078-82a7-29db3b9a8984`) and SQLite isolation (`aeeefc5f-56f1-4da9-a798-3ced3ae40f38`); MCP reported all three ready. A follow-up query returned source-linked excerpts for experimental selection effects and serialized SQLite writes. No local material or measurements were sent. Use the primary links above rather than quoting the notebook synthesis as evidence.

The duplicate-work and maintainer-load follow-ups separated synthetic coordination (Grite) from real LLM runs on a benchmark (PASC). Grite's §§4–6 describe seeded actors and report that leases alone did not prevent rediscovery in the tested task pool. PASC's published abstract describes a two-agent shared-workspace experiment, not open contributor onboarding. Neither measures Nexus maintainer minutes. The notebook also extrapolated METR to unsolicited PR review; discard that extrapolation. METR's early trial measures experienced developers doing their own tasks, not maintainers triaging agent contributions. The primary preprint was added as a public URL (`b5d38652-0374-4671-9bba-2ce41dc10733`, ready). Keep both METR and Paradis as reasons to measure human time directly, not as priors for its sign.

## Hypotheses and measurement

- **H1:** Lease plus visible durable completion reduces redundant starts and finishes. Exercise deterministic scripted contention first; separately compare real agents at fixed budget. Distinguish expired work, cap denials and semantic duplicates missed by exact comparison.
- **H2:** A separate review gate and cap reduce maintainer interruptions without sacrificing accepted work. Record blinded acceptance, defects found after approval, review and cleanup minutes, and unwanted writes (target zero).
- **H3:** A tool-aware prompt plus manual fallback improves first successful contribution without overclaiming access. Count successful installs, first successful discovery, steps, breakpoints, time, and uninstall/revocation effectiveness for actual tools.

### Three-arm experiment (not run)

The [frozen pilot protocol and task manifest](rehearsals/three-arm.md) instantiate this design. Offline setup passed; the matched trial has not run.

1. Select consenting maintainers and freeze a pool of text-report tasks, public sources, exact revisions, and a rubric for actionable and correct findings. Include overlapping and non-overlapping tasks. Use separate scratch areas and collect outputs privately in all arms; evaluation never writes to GitHub. Pre-register runs, random seed, caps, and the maximum acceptable human time before drawing conclusions.
2. Repeat each task pool in randomized arm order: **solo** (one contributor), **independent** (two contributors without shared state), and **Nexus** (two contributors with admission, leases and visible durable state). Use the same model version, source access, instructions apart from coordination, total token/cost and wall-time ceilings including coordination calls, and independent human review budget. Stop at the first ceiling. Reset state between runs and keep partial, timed-out and zero-output runs. Equal ceilings do not imply equal spend: record actual consumption.
3. Give assessors shuffled reports without arm labels and use the same checklist in every arm. Separately time consented active maintainer work: setup, intake, review, questions, and cleanup. Measure unique correct actionable outcomes per run, duplicate starts and semantically overlapping findings, post-review errors, wall time, total spend, and interruptions. Count old/invalid reservations and cap denials separately from useful work. Keep the no-agent option when the value fails to cover human time and spend.
4. Report paired per-pool differences with uncertainty and retain outliers. Prefer a Pareto comparison: promote only if Nexus improves an agreed outcome without an unacceptable loss on other measures. If maintainers choose a composite value score, record weights beforehand and show sensitivity. Connection checks, scripted contention, and file/HTTP fixtures cannot satisfy this comparison or the live GitHub gate.

## Round 2 — 2026-11-26: should reports awaiting a human hold admission?

Question: once a report is submitted, the lease ends. Should it still count against `active_limit` while it waits for review or for the maintainer? Without that, a fast pool of agents can fill the review queue with no bound other than the task catalogue.

| Source | What it supports | What it does not establish |
| --- | --- | --- |
| [Li, Zhang and Hassan, AIDev, v1](https://arxiv.org/abs/2507.15003v1) (abstract checked) | Over 456,000 agent PRs across 61,000 repositories: agents are faster but their PRs are accepted less often, and one developer opened as many PRs in three days as in three years. Agent output can outrun human acceptance. | A safe queue depth for any given project. |
| [Google SRE, handling overload](https://sre.google/sre-book/handling-overload/) (round 1) | Reject excess work at admission rather than letting queues grow without bound. | How many reports one maintainer can handle. |
| [Sarkar, before the PR, v1](https://arxiv.org/html/2606.19616v1#S4) (round 1) | Completion state must be shared, not just locks; otherwise finished work is redone. | That a review-aware cap preserves accepted output. |

NotebookLM answered that pending reviews should count as WIP. It quoted Little's law from an "Architecture Nexus" document that belongs to this project, so it is not independent evidence and is excluded. It also quoted practitioner blogs with uncontrolled before/after figures (for example "WIP 15→8, cycle time −40%"); these are not cited as findings. The counter-example it raised is `pequalnp.com`, where a formal checker replaces human review on the intake path. That supports dropping the human-held slot only when a machine verifier fully decides acceptance, which is not the case for Nexus text reports.

**Decision:** `active_limit` now counts open leases plus non-withdrawn reports that await review or the maintainer's decision. A rejection, a maintainer `decline`, an authorization or a revocation releases the slot. The limit is now a bound on the work waiting for humans. Setting it is the maintainer's choice, not a derived optimum.

**H4 (new):** with that bound, the number of reports waiting for a human never exceeds `active_limit`, and the share of accepted reports does not fall compared with an unbounded queue at equal budget. The first part is enforced by tests. The second is **not run**; it belongs to the three-arm experiment.

## Round 3 — 2026-11-26: where does a project declare consent?

Question: what should prove that a project agreed to Nexus, and which issues and files it covers, so that a maintainer can withdraw without the operator?

NotebookLM compared three sources of consent: a committed configuration file, issue labels, and the App installation alone. It reported that labels can be changed with the triage role and that installation scope is repository-wide. I checked these points against primary documentation rather than against its citations:

| Source | What it supports | What it does not establish |
| --- | --- | --- |
| [GitHub repository roles](https://docs.github.com/en/organizations/managing-user-access-to-your-organizations-repositories/managing-repository-roles/repository-roles-for-an-organization) (fetched) | Triage is "recommended for contributors who need to proactively manage issues, discussions, and pull requests without write access" and can apply labels; pushing needs Write. A label is a weaker signal than a commit. | How projects actually assign triage. |
| [GitHub compare two commits](https://docs.github.com/en/rest/commits/commits#compare-two-commits) (fetched) | Without pagination, the commit list stops at 250 commits; changed files stop at 300 for the whole comparison; renames carry `previous_filename`. A truncated response must be read as "possibly changed". | Semantic conflicts: a file outside the task's paths can still change what the report means. |
| [GitHub permissions for Apps](https://docs.github.com/en/rest/authentication/permissions-required-for-github-apps) (round 1) | App permissions apply to the whole repository, not to an issue or path. | — |
| Dependabot and Renovate (`.github/dependabot.yml`, `renovate.json`; NotebookLM, not re-verified) | Precedent for opting in through a file on the default branch. | That their users treat the file as consent rather than configuration. |

**Contradictory point kept:** the path rule only detects textual changes. A report about `CONTRIBUTING.md` can become wrong because of a change to a build script it does not name. Listing narrow paths reduces false staleness but accepts this risk. The fallback without paths stays strict.

**Decision:** [ADR 002](adr-002-repository-consent.md). **H5 (new):** checking a maintainer-owned file at the exact publication commit blocks every publication not covered by current consent, and makes no write. This is enforced by tests with a GitHub double. It is **not yet observed** live: it needs the App installation and the file merged on the fork.

## Round 4 — 2026-11-26: which signals show a real, unclaimed need?

Question: from what an existing project already publishes, how can Nexus propose work without duplicating or overrunning human work?

NotebookLM ranked signals this way:
- reproducible CI failures, formal task desks and typed dependency graphs are reliable;
- labels are fragile;
- an assignee, a linked open pull request or an active lease means a human or agent is on it;
- agents given vague specifications "produce a plausible, internally consistent" result instead of asking (*Specs In, Software Out*, quoted by the notebook, not re-verified).

Its claim that labels are unreliable rests on a vendor blog and a forum post. I therefore did not use it as evidence. I used GitHub's documented role model instead (round 3).

| Source | What it supports | What it does not establish |
| --- | --- | --- |
| [GitHub issue event types](https://docs.github.com/en/rest/using-the-rest-api/issue-event-types) (fetched) | `cross-referenced` events carry `source.issue`; a pull request is recognized by `source[issue][pull_request]`; `connected` marks a manually linked PR. | That every PR working on an issue references it. |
| [GitHub issues API](https://docs.github.com/en/rest/issues/issues) (fetched) | "Every pull request an issue": the `pull_request` key identifies them; issues expose `assignees`. | — |
| [GitHub REST rate limits](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api) (fetched) | Unauthenticated reads: 60 per hour per IP. This sets the scan bound. | — |
| [Tan, Zhou and Sun, *A first look at good first issues on GitHub*, ESEC/FSE 2020](https://dl.acm.org/doi/10.1145/3368089.3409746) (bibliographic record only, contents not checked) | Labels intended for newcomers are an object of study in their own right, not a uniform signal. | Any figure; not cited for one. |
| Red Hat, [*Don't lick the cookie*](https://www.redhat.com/en/blog/dont-lick-cookie) (practitioner) | Claiming without doing is a known community anti-pattern. This is why a free-text claim is neither honored nor issued; Nexus leases expire. | Its frequency. |

**Contradiction kept:** skipping every issue with a linked PR may hide abandoned PRs that a helper could rescue. The skip reason is reported, so the maintainer can still select such an issue by hand.

**Decision:** [ADR 003](adr-003-need-discovery.md). **H6 (new):** proposals never include an issue that is assigned or has an open linked PR at scan time, and never write. Enforced by tests. Observed read-only on GitHub: the fork and the upstream both return `no_consent`, because neither has the file. With an injected consent for issues 1 and 2, a replay against the live upstream proposed #1 and skipped #2 as a pull request, in 6 requests. Whether proposals save the maintainer time is **not run**: it is part of the three-arm experiment.

## Round 5 — 2026-11-26: should Nexus carry code, and how?

Question: can a contribution be a ready change without new GitHub permissions, more review load, or running untrusted code?

NotebookLM compared three options: (a) the coordinator opens PRs, (b) a validated diff is posted as a comment, (c) text only. It found the least friction in (a), but also the highest review volume. It described (b) as more manual for the maintainer.

| Source | What it supports | What it does not establish |
| --- | --- | --- |
| [git-apply documentation](https://git-scm.com/docs/git-apply) (fetched) | A patch "that affects outside the working area … is rejected as a mistake (or a mischief)" unless `--unsafe-paths`; `--numstat` lists paths without applying; `--check` applies nothing. | That `git apply` is safe on hostile input by itself. Hence the second layer: Bubblewrap, a `.git`-free tree, and an explicit refusal of modes, symlinks, renames and binaries. |
| [GitHub App permissions](https://docs.github.com/en/rest/authentication/permissions-required-for-github-apps) and [Create a pull request](https://docs.github.com/en/rest/pulls/pulls#create-a-pull-request) (fetched) | Opening a PR needs write access to a head branch. It triggers notifications and CI. | How much load one PR adds for a given project. |
| Sarkar, [*Before the Pull Request: Mining Multi-Agent Coordination*](https://arxiv.org/abs/2606.19616), arXiv 2606.19616 (abstract read) | "Autonomous coding agents now open millions of pull requests, yet large-scale studies find their PRs are produced faster but accepted less often." | Any figure; the cited study was not read. |
| [Bubblewrap](https://github.com/containers/bubblewrap) (observed locally) | `--unshare-all` gave `Network is unreachable` and only `lo` on this host. | Isolation against kernel exploits; nothing untrusted is executed. |

**Contradiction kept:** the notebook cites sources that ask for direct PRs (`pequalnp-proofs`: "never … send a proof by comment; a proof goes in as a pull request"; *EvoGit*: map collaboration to native Git primitives). They come from projects that opted into agent PRs and run merge queues. Nexus adapts to projects that did not, so PRs stay a per-project opt-in for later. They are not the default.

**Decision:** [ADR 004](adr-004-patch-artifact.md). **H7 (new):** a patch reaches a reviewer only after a sandboxed check at the pinned commit confirms that every changed file is a plain text file inside the task's paths. A failed check releases capacity. Publication also requires the project's `patch` consent. Enforced by tests, with mutation checks: removing the forbidden-change filter or the scope check makes tests fail. Rehearsal on a fresh ledger against the real pinned `FRGMesh/anyps5` commit: [script](rehearsals/patch_capacity.py), [output](rehearsals/patch_capacity.out). **Not run:** whether maintainers accept patches more often than reports.

**Round 5 follow-up (observed):** a real Antigravity/Gemini agent produced a patch for a `docs/dev/BUILD.md` task. The sandboxed check passed it: in scope, applies at the base. The independent reviewer rejected it on meaning: it merged the relinker-only and full build directories, against the file's own instruction. This supports both halves of H7: the check is necessary to bound form and scope, and it is not sufficient. One run is an anecdote, not a rate.

## Round 6 — 2026-11-26: what to ship before scaling?

NotebookLM reconstructed a roadmap from the indexed *SwarmOS* §8.2 and *Architecture Nexus* §8 documents. The Studio report was not accessible through the current MCP, so this is neither a transcript of that roadmap nor independent evidence. Its proposals (Git-backed memory, semantic intake, clusters, distributed transport, and richer publication gates) were compared against the pilot's [release gates](roadmap.md).

- **Value and voluntary budgets.** The authors' [Cui et al. study summary](https://www.microsoft.com/en-us/research/publication/the-effects-of-generative-ai-on-high-skilled-work-evidence-from-three-field-experiments-with-software-developers/) reports 26.08% more completed tasks (SE 10.3%) across three enterprise experiments involving 4,867 developers using code completion. METR's early OSS trial measured task time for experienced maintainers instead; its [2026 update](https://metr.org/blog/2026-02-24-uplift-update/) warns that selection and concurrent work make the later estimates unreliable. Together they justify tracking accepted work **and** human time, not a Nexus speedup or a mandatory spending allocator. Development has no user-defined monetary ceiling; a matched experiment still needs a common resource ceiling and must report actual usage, including unknown or unavailable token/cost data. Treat a contributor's future help limit as voluntary, separate from project quotas, and only call it enforced if the harness can meter and stop the work.
- **Protect human work at the point of action.** Reuse the existing bounded timeline scan before a new dispatch, rather than subscribing to webhooks or adding a scheduler for the pilot. **H8:** a newly visible open PR or an inconclusive timeline must block publication without spending the grant. Verify with a second-page link, a saturated or malformed timeline, and a retry after the refusal. This does not prove visibility of unrelated or private work.
- **App scope.** The [GitHub token documentation](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-an-installation-access-token-for-a-github-app) distinguishes the installation's maximum authority from the repositories and permissions of a particular token. Both are needed: token restriction alone leaves the App key able to mint broader credentials. Keep the live gate blocked while the installation is set to all repositories.

Added only the two public URLs above to the reference notebook: Cui et al. (`55ed224c-59c4-426c-bb15-4f704f0db94f`) and GitHub token scoping (`f8fa41fe-a81d-48f9-a1e6-90e73d52c4a8`). MCP reported them ready and the notebook listed 128 sources. No local file or non-public deployment detail was sent.

## Round 7 — 2026-11-26: distinguish setup from useful work

NotebookLM found no direct benchmark for local MCP newcomer onboarding. Its suggested [MAST study](https://arxiv.org/abs/2503.13657v3) distinguishes system design issues, agent misalignment and verification failures across seven frameworks; that taxonomy is useful for diagnosis, not a usability result for Nexus. The authors' [Fronchetti et al. paper](https://doi.org/10.1145/3611643.3616288) reports that over 75% of manually reviewed projects omitted guidance for newcomer task selection and workspace setup. This concerns OSS contributor docs, not non-technical MCP users. It argues for testing both finding work and setting up the client, not for assuming another guide will suffice. Added the [public author copy](https://www.marcoagerosa.com/papers/FSE2023_Fronchetti.pdf) to NotebookLM (`fb8124f0-4501-4f80-a47e-85a81067d327`, ready).

**Decision:** score first authenticated discovery independently of MCP connection and contribution quality. The [automated clean run](rehearsals/clean-install.md) validates the installation and access mechanics; only an observed first-time volunteer can establish whether the instructions are sufficient. Do not add an onboarding service before that trial identifies a problem it would solve.

## Round 8 — 2026-11-26: separate parallelism from coordination

- NotebookLM surfaced two already indexed studies. The publisher's [Özaytürk and Buzluca abstract](https://doi.org/10.4230/LIPIcs.ESEM.2026.18) confirms the isolated solo and silent two-agent comparators. The latter shared a Docker container and Git tree; it was not an isolated, non-communicating work pool like our independent arm. The study measures bug-fix outcomes on assigned tasks, not open intake or human review. Its results do not establish Nexus's productivity.
- [Kim et al., v3 §4.1 and Fig. 2](https://arxiv.org/html/2512.08296v3#S4) matched maximum aggregate iterations, measured tokens, and reported worse SWE-bench Verified results for all tested multi-agent architectures than solo. Matching iterations is not the same as enforcing a token cap. Their controlled benchmark is a reason to keep a strong solo comparator, not a prediction for short documentation reports.

**Decision:** fix the task menus and standardize aggregate ceilings; let contributors select tasks from those menus. Compare Nexus with both solo and independent contributors, record duplicate starts separately from overlapping findings, and judge reports blind to arm. This tests text-report coordination and intake; it does not test GitHub task discovery, publication, or scaling beyond two contributors. No duplicate sources were added to NotebookLM.

## Round 9 — 2026-11-26: separate observation from budget enforcement

NotebookLM pointed to Google's [Handling Overload](https://sre.google/sre-book/handling-overload/) and [Addressing Cascading Failures](https://sre.google/sre-book/addressing-cascading-failures/). The primary chapters distinguish actual resource consumption from request count, explain how retries amplify load, and recommend propagating deadlines and cancellation. Their adaptive throttling limits overload probabilistically; it is not a deterministic token ceiling or evidence of cancellation at a model provider. The [local OpenCode probe](rehearsals/three-arm.md#offline-harness-qualification) confirms why the distinction matters here: configured step limits did not cover all wire attempts or tool calls, and missing usage did not block the next dispatch.

**Decision:** keep experiment enforcement outside Nexus's production quotas. Prefer a single trusted request and tool dispatcher to a browser workflow, a prompt, or a proxy that sees only model traffic. Before each dispatch reserve a conservative input-plus-output bound against the worker's partition; charge each attempt; settle only from complete, non-overlapping usage; stop on unknown usage, and retain but do not score late output. Treat the provider's input bound, output cap, cancellation and billing as adapter-specific claims to verify, not consequences of the local rehearsal.

## Round 10 — 2026-11-26: constrain capabilities without assuming better answers

NotebookLM surfaced [*Agentic Proof and Property-Based Testing via Property-Templates*, RQ3](https://arxiv.org/html/2607.09072v1). The paper reports 387/400 faithful outputs with a template versus 371/400 without it. It changed the generated artifact's structure, not shell permissions. Conversely, the [mini-SWE-agent authors](https://mini-swe-agent.com/latest/) report strong benchmark results with a minimal command-running agent. Its scope includes implementing and running code, unlike our text-report trial; neither source isolates the effect of restricting tools on identical Nexus tasks. NotebookLM's other guardrail examples did not establish that effect either.

**Decision:** retain narrow task actions to enforce the allowed scope, not as a quality optimization. The scripted dispatcher refusal tests check access and metering; the [real-engine smoke](rehearsals/three-arm.md#offline-harness-qualification) separates completed usage from cancellation and does not establish useful output. Keep the same source access across arms and leave the quality effect unmeasured until a qualified run receives blind review. No source was added in this round.

## Round 11 — 2026-11-26: distinguish client stop from backend stop and accounting

NotebookLM pointed to the [Google SRE chapter on cancellation propagation](https://sre.google/sre-book/addressing-cascading-failures/#cancellation-propagation) and [A2A's Cancel Task operation](https://a2a-protocol.org/latest/specification/). The SRE chapter argues for propagating cancellations to avoid doomed work. A2A explicitly says cancellation may fail. The [MCP cancellation specification](https://modelcontextprotocol.io/specification/2025-11-25/basic/utilities/cancellation#behavior-requirements) says receivers should stop and free resources, and allows ignoring cancellation if the request cannot be cancelled. None of these supplies a token receipt. The pinned [llama.cpp release path](https://github.com/ggml-org/llama.cpp/blob/8f83d6c/tools/server/server-context.cpp#L2130-L2138) has a cancellation branch that can release a matching task, but that branch's existence does not prove a disconnected request stopped or yielded final usage. The local probe stopped waiting while a slot was still busy and the usage remained unknown.

**Decision:** track output eligibility, backend termination and accounting as distinct outcomes. A closed client socket alone cannot qualify an arm. Keep unknown interrupted resource use explicitly unscored under [protocol v1](rehearsals/three-arm.md#runs-and-ceilings); this is different from a fully metered run with no useful output. Do not add a distributed cancellation protocol for a local experiment. No source was added in this round.

## Round 12 — 2026-11-26: test the native chat framing in isolation

NotebookLM did not identify an indexed primary study that isolated formatting from instruction content. [Sclar et al.](https://arxiv.org/abs/2310.11324) found sensitivity to meaning-preserving formatting in few-shot benchmarks and weak correlation across models. Conversely, [*Flaw or Artifact?*](https://arxiv.org/html/2509.01790v1) found that rigid answer matching and likelihood scoring explain much of the observed variation for the models and benchmarks they tested. Neither study establishes that a native chat template improves an agent's ability to follow a tool contract. Here, accepting a malformed action would change the actual tool contract, not just the scoring method.

**Hypothesis and check:** use the [pinned engine's `/apply-template`](https://github.com/ggml-org/llama.cpp/blob/8f83d6c/tools/server/README.md#post-apply-template-apply-chat-template-to-a-conversation) for the unchanged synthetic Ministral user prompt. The installed GGUF template also injects its default system message when the first role is `user`, so this tests the stock framing, not delimiter changes alone. Keep token admission and action validation unchanged; check the real receipt and source citation separately. The earlier raw run was stopped externally at 100 s, so the native probe using the full existing arm deadline cannot establish a latency improvement. Native special-token parsing is for this trusted fixture only; keep it disabled for untrusted project transcripts until token boundaries are verified. See the [probe](rehearsals/three-arm.md#offline-harness-qualification). Both public arXiv URLs were added to the notebook and reported ready (`6e4c1efe-e3cb-4699-91cf-fcc6e473d71e`, `32426abe-089b-4d31-bac5-97403c38c213`); no local contents were sent.

**Result:** four of four receipts matched the engine logs, but `submit` still omitted `report`. Framing alone did not qualify the runner. The next synthetic question is whether giving the model the existing action contract explicitly is enough, without changing the validator or supplying the task answer.

## Round 13 — 2026-11-26: show the action contract without changing it

NotebookLM pointed to [MCP tool input schemas](https://modelcontextprotocol.io/specification/2025-11-25/server/tools) and found no evidence that valid syntax establishes correctness or authority. The specification separately requires servers to validate inputs and enforce access control. The [pinned llama.cpp grammar documentation](https://github.com/ggml-org/llama.cpp/blob/8f83d6c/grammars/README.md#json-schemas--gbnf) says the completion schema restricts generation but is not injected into the prompt. [OpenAI's Structured Outputs announcement](https://openai.com/index/introducing-structured-outputs-in-the-api/) reports high shape compliance in its own evaluations, but explicitly warns that the values can still be wrong. That result is not evidence for Ministral, nor a reason to replace dispatcher checks. Both public upstream sources were added to the notebook and reported ready (`fb75b2c4-d171-49f2-b707-b204aac43a97`, `ea86c3a2-dec2-4f37-9af2-36a57ed72940`); no local content was sent.

An alternative worth testing if prompt examples prove insufficient is explicit decoder enforcement of the existing contract. [JSONSchemaBench, Table 8](https://arxiv.org/html/2501.10868v3) found that llama.cpp with constrained decoding improved two of three reasoning scores and tied the third versus unconstrained Llama 3.1 8B in that setup. Conversely, [*Let Me Speak Freely?*](https://arxiv.org/abs/2408.02442) reports declines in reasoning under stricter format restrictions in its own tests. Measure report quality separately from schema compliance. Neither result establishes source fidelity or authorization. JSONSchemaBench was added as a public source and reported ready (`f9ba87d1-7fa4-45f7-8f1e-fe43742cb978`).

**Hypothesis and check:** show the exact keys for each action in the synthetic prompt, including a `report` string with placeholders rather than the answer. Keep the native framing, generic JSON-object grammar, quotas and dispatcher unchanged. Require the report to be admitted and cite the actual source line; compare each receipt with the engine log independently. See the [probe](rehearsals/three-arm.md#offline-harness-qualification).

**Result:** the explicit prompt did not reach `read` or `submit`. After a successful `start`, the model kept repeating it despite nine refusals; 10 of 11 requests had matching receipts and the deadline left one unknown. The observed failure is action selection, not output shape. A decoder that only enforces the same shapes would still admit these repeated `start` objects; the dispatcher is responsible for refusing them. Before another full run, test whether prominently presenting the last action result or current reservation state changes the model's next choice on a synthetic transcript. Keep all action shapes available and do not prescribe the next action.

## Round 14 — 2026-11-26: show the latest reservation result

NotebookLM found evidence for providing feedback but no indexed experiment isolating its placement for action selection. The [PASC paper](https://doi.org/10.4230/LIPIcs.ESEM.2026.18) compares a shared peer-activity feed with no such feed in a two-agent repair setup, not near versus far placement. [*Lost in the Middle*](https://arxiv.org/abs/2307.03172) varied information position in retrieval and question answering, not interactive tool use. [ReAct](https://arxiv.org/abs/2210.03629) tested acting with observations and reasoning across several tasks, not moving an otherwise identical reservation receipt. The latter two public sources were added and reported ready (`01e36d75-eb4b-47e9-bce1-5ff8b2138266`, `86863055-ad6c-44c5-81d8-40b681749cd1`); no local content was sent.

**Result:** in the [one-turn probe](rehearsals/three-arm.md#offline-harness-qualification), a prominent reservation receipt and a neutral action menu were followed by an authorized read rather than a repeated `start`. The read covered the heading only, and the sole receipt matched. This checks selection in one known state, not usefulness, placement alone, or multi-step reliability. A next synthetic check can test whether the model advances to unread content after a partial read, without supplying the finding or making that action mandatory.

## Round 15 — 2026-11-26: does a partial observation lead to another read?

A source-limited NotebookLM follow-up found neither ReAct nor *Lost in the Middle* isolates that decision. [FLARE](https://arxiv.org/abs/2305.06983) and [Self-RAG](https://arxiv.org/abs/2310.11511) offer alternatives to an unrestricted next-action prompt: confidence-triggered retrieval and trained retrieval decisions, respectively. Their long-form generation or benchmark results do not establish that this reference model will advance a bounded line read. Test the simpler existing interface first, without training, a retrieval service, or automatically expanding the model's read scope. Both public sources were added and reported ready (`94882f51-3d4c-4d39-a5ad-3d96fe763240`, `7a42c0bc-4e25-4e50-8e6f-880fd27ed301`); no local content was sent.

**Result:** from a replayed heading read, Ministral selected line 2 and the dispatcher admitted it; the sole receipt matched the engine. This checks retrieval selection for one fixture, not report accuracy or repeated operation. Keep the interface unchanged for the next synthetic check: can the model submit a cited report once the evidence is actually in its transcript?
