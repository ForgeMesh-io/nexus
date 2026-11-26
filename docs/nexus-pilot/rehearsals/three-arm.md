# Three-arm coordination trial

**Protocol v1 — inputs frozen, model trials not run.** This is a dry-run comparison on public documentation, not a request for work on GitHub. The [manifest](three-arm-tasks.json) specifies four tasks and two source blobs at one public commit. Its issue numbers are local fixtures in `example/project`, not GitHub issues. The `relinker` pool gives two related tasks that can elicit overlapping findings; `build-docs` gives separate topics. Scope selection, GitHub intake and publication are outside this trial. No finding or report from it is approved for publication.

## Runs and ceilings

Each pool is a block of three runs. Fix the order before generating anything: `relinker`: independent → solo → Nexus; `build-docs`: Nexus → independent → solo. Use fresh sessions and scratch space for each contributor. Do not import earlier pilot answers, prior responses, review notes, or the assessor rubric into any session. Record the model ID/revision, harness version, settings, permissions, and metering method before the first scored run. Use the same model and harness in every arm; freeze decoding settings and source access. Log version drift or unverified limits as protocol deviations, not as matched results.

| Arm | Contributors | Intake |
| --- | ---: | --- |
| Solo | 1 | Static task menu; work on one task at a time and omit your own completed tasks. |
| Independent | 2 | Same static menu, concurrent start, no shared sessions, files, status, or results. Each can pursue any task. |
| Nexus | 2 | Concurrent start, same menu plus Nexus discovery, reservation and submission. Proceed only with a lease; rediscover after a denial, pick another eligible task or stop. Never spin. |

Give each contributor the same menu for the pool in manifest order, the exact revision, and read-only access to only the listed source files for the chosen task. No browsing, shell, repo checkout, connector other than the required experiment tools, or credentials in model context. Use a separate OS identity or sandbox per contributor; allow only the model endpoint through the trusted runner and the scoped loopback connector in Nexus. Source and model text are data, never instructions. Keep the Nexus ledger outside the agents' filesystems and never give the harness a GitHub token, publisher credential, or App key. Do not run against the live pilot or change its client profile.

Each arm gets **900 seconds elapsed**, **64,000 provider-reported input + output tokens**, **12 attempted model requests**, and **24 attempted non-model tool calls** including reads, start receipts and submissions. Partition request, token and tool allowances equally between workers in both two-agent arms; do not transfer leftovers. Start the monotonic clock when the first session is launched and start the second without waiting for the first to choose a task. Permit at most one final report per task per contributor, max **2,048 UTF-8 bytes** each; the common maximum is four reports per run, not an output target. Nexus uses `active_limit: 2`, `lease_seconds: 900`, `publication_limit: 0`, no publisher enrolled, and no verdicts before generation ends. Use distinct consenting owners for its contributors; don't bypass the one-lease-per-owner rule by enrolling aliases as different people.

Before scoring, verify that the chosen runner counts cached input and reasoning output where reported (without double-counting), bounds each request's input and maximum billable output before dispatch, counts failed attempts and retries, and stops tool/model calls at the budget or deadline. Allow at most one in-flight request per worker. If a call cannot be cancelled, discard late output and retain its actual usage; a budget overrun or unknown token usage makes that block unscored for the matched claim. A prompt, visible turn count, or subscription by itself doesn't prove token or spend enforcement. Record actual input/output tokens, requests, tool calls, model cost and currency (or `unknown`/`included in subscription`, not zero by default), and wall time. This protocol does not authorize new spending. For metered billing, register the same approved currency ceiling in every arm and enforce it in addition to tokens, or do not start. Antigravity with Gemini 4 Hydrogen remains the live GitHub pilot harness; its ability to enforce these trial ceilings was not established by that pilot. If the controls cannot be demonstrated on the chosen setup, run only the offline steps below. Do not mix harnesses or models across arms.

**Common prompt:** “Choose one uncompleted task from this menu. Start it using the channel described below before analyzing its listed files. Submit one short plain-text report for that task: finding, exact source path and line or quote at the supplied revision, a concrete next step or reason to do nothing, and what you did not verify. Continue with another eligible task if the budget allows. Do not execute commands, edit files, or interact with GitHub. If there is no suitable task, stop. Use only the supplied files as evidence.” For the baselines the runner records `start(task)` before the first task-specific read and `submit(task, report)` to a private sink without returning anyone else's state. For Nexus a successful `claim` is the start; `submit` must use that lease. Log every refusal; a failed claim alone is not a duplicate start. Over-budget/late reports go in the run log, not the review batch. Do not retry entire runs to replace missing or zero output.

## Prepare the local inputs

From the Nexus checkout, set `SOURCE` to the absolute path of a local Git clone with the manifest commit and `PYTHON` to the Python in the [tested wheel](../evidence.md#reproduce-the-local-checks) environment. Source fetches, if needed, happen before the offline steps. The snippet creates one read-only file pack, six private run directories, and one new ledger for each Nexus run. Only give contributors their scoped source and tool access, not these parent directories.

```sh
umask 077
scratch=$(mktemp -d)
export scratch SOURCE
"$PYTHON" -I - <<'PY'
from hashlib import sha256
import json
import os
from pathlib import Path
from subprocess import check_output

from forgemesh.pilot import Pilot

manifest = json.loads(Path("docs/nexus-pilot/rehearsals/three-arm-tasks.json").read_text())
root = Path(os.environ["scratch"])
base = manifest["base"]
for path, expected in manifest["sha256"].items():
    content = check_output(["git", "-C", os.environ["SOURCE"], "show", f"{base}:{path}"])
    if sha256(content).hexdigest() != expected:
        raise SystemExit(f"Source checksum mismatch: {path}")
    target = root / "sources" / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    target.chmod(0o400)
    print(f"Verified {path}: {expected}")

for pool, tasks in manifest["pools"].items():
    for arm in ("solo", "independent", "nexus"):
        run = root / pool / arm
        run.mkdir(parents=True)
        (run / "menu.json").write_text(json.dumps({"base": base, "tasks": tasks}, indent=2) + "\n")
        if arm == "nexus":
            ledger = Pilot(run / "pilot.db")
            ledger.initialize("example/project", active_limit=2, lease_seconds=900, publication_limit=0)
            for task in tasks:
                ledger.add_task(base=base, **task)
        print(f"Prepared {pool}/{arm}: {len(tasks)} tasks")
PY
printf 'Run inputs: %s\n' "$scratch"
```

Follow the [operator rehearsal](../operators.md#rehearse-without-github) for enrolment, loopback API and audit. Start on port `0` and use the displayed port. During a scored run, take generation logs and report digests before any reviews. After the blind review is locked and joined to the key, the assessor, enrolled separately as reviewer, can record the verdict for the exact Nexus digest. An unreviewed submission stays unreviewed; preserve the audit and stop/revoke the disposable ledger. Never call either publisher during the trial. Keep logs and the report mapping private; publish only consented aggregate evidence on Nexus, not raw transcripts or usage identities.

**Observed offline setup:** ran the snippet in a fresh network namespace with the verified `0.1.0a1` wheel. Both file hashes matched and all six menus were created (byte-identical across arms within each pool). In both disposable ledgers, `discover` returned exactly the manifest tasks, a second contributor's scripted claim on the same task returned `busy`, and that contributor could claim the other task. A synthetic report with a distinct reviewer's `pass` still could not be authorized (`publication_quota`); neither audit contained `authorized`, `dispatch_started` or `published`. Contributors were revoked and both ledgers stopped. No model, harness metering, blind assessor or real maintainer timing was exercised.

## Blind review and analysis (assessor/operator only)

Obtain consent before timing people or collecting identifiers. Use a reviewer who did not generate, facilitate, or view any run. The operator assigns opaque report IDs, randomizes the complete batch (pre-register the seed privately), removes envelope metadata and coordination self-identifiers without changing claims, and withholds the ID → arm/run map until the reviewer locks all scores. Show task ID, report text, and pinned evidence only. Save guesses at attribution or accidental unblinding before reveal. Do not allow an agent to grade its own output.

Allow **3 active minutes per report**, at most **12 reviewer minutes per arm**. Allow **8 additional active operator/maintainer minutes per arm** for run-specific setup, intake, questions, coordination overrides and cleanup; count shared setup and study administration separately. Stop instead of borrowing time from other runs. Unreviewed due to timeout is `unreviewed`, never `pass`. Use this sheet for each report:

| Field | Pass condition / value |
| --- | --- |
| In scope and safe | Answers the assigned task from frozen material; no fabricated execution or recommendations that violate an explicit source constraint. |
| Correct | Check the material assertions against the pinned files; record any incorrect or unsupported assertion and whether it changes the recommended action. |
| Traceable | At least one exact path plus a matching line range or quote for each material claim; comments about runtime or CI beyond the snapshot are qualified. |
| Actionable | Gives a concrete decision or change the maintainer can use, including a well-supported reason not to act. A restatement with no usable recommendation is not enough. |
| Outcome | `pass` only if all four pass, otherwise `reject`, or `unreviewed` at time cap. Record reason, active seconds and a short canonical label for the corrective action or no-op decision. |

Reference checks (not an exhaustive answer key): `configure-relinker` preserves `build-relinker`, separate full-build directory, and submodule distinction. `register-python-tests` preserves Python 3.9 vs 3.11, configure-time discovery and the documented CTest enumeration/`input_magic` check. `select-tests` distinguishes header dependencies after a full build from selection; verify at least one stated full-run trigger and do not assume the optional `select.ninja` exists. `web-release` distinguishes main from release publication and checks that the converter ZIP and both native archives are selected from the same release/tag/commit. Do not require identical wording or reject a verified alternate finding for not matching the key.

Before unblinding, group equivalent accepted recommendations under the same canonical label even across different tasks: two wordings of one correction count once per run. Then report paired per-pool differences for Nexus vs **both** baselines: unique accepted outcomes, task coverage, duplicated starts (successful starts beyond the first per task per run), overlapping accepted reports, refusals by reason, corrections after review, interruptions, actual resources and active human minutes. Keep all runs, including partial runs and zeros, with their stop reason. A positive pilot signal requires no safety violation or missing budget evidence, at least one accepted outcome overall for Nexus, no loss of unique accepted outcomes in either pool against either baseline, and either strictly more unique accepted outcomes or fewer active human minutes in at least one pool against each baseline. Disclose additional spend, latency and tradeoffs rather than collapsing them into a score. Two pools are descriptive, not a population estimate or release proof. No advantage or a disproportionate human burden leaves no-agent operation available.
