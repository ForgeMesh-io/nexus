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

## Offline harness qualification

**OpenCode v2.0.21 using `steps` is not qualified.** A [scripted loopback provider](opencode-metering.py) sent three tool calls per turn, omitted usage on the first successful primary response, returned a 429 on the final configured step, and delayed the retry response. Two sessions reached the provider concurrently in each two-worker arm. The baselines returned actual file reads; the Nexus arm returned actual MCP discovery results from a disposable ledger with publication disabled. This is a harness characterization, not a run on the frozen tasks.

From the checkout on Linux, with `PYTHON` set as above and OpenCode v2.0.21 on `PATH`:

```sh
unshare --user --map-root-user --net bash -eu -c '
  ip link set lo up
  "$1" -I docs/nexus-pilot/rehearsals/opencode-metering.py
' bash "$PYTHON"
```

```text
opencode v2.0.21
solo: HTTP attempts=14/12 (13 primary), tool results=33/24, reported primary tokens >= 88220/64000, continued after missing usage=1, late outputs rendered=1
independent: HTTP attempts=16/12 (14 primary), tool results=30/24, reported primary tokens >= 80200/64000, continued after missing usage=2, late outputs rendered=2
nexus: HTTP attempts=16/12 (14 primary), tool results=30/24, reported primary tokens >= 80200/64000, continued after missing usage=2, late outputs rendered=2
```

HTTP counts include failed attempts, retries and auxiliary title requests. The token lower bounds sum only mock-reported primary usage: 8,000 input + 20 output per measured response, including 6,000 cached and 10 reasoning tokens already in those fields. This calculation is external, not proof of OpenCode's internal token accounting. The late marker was rendered after an external 250 ms observation cutoff on the retry; no native run deadline or provider cancellation was configured or demonstrated. `steps` limited the agent loop and the request carried `max_completion_tokens: 32`, but neither enforced the shared budget. No real model, credentials, billable usage, human timing or GitHub writes were involved.

**Offline gate and action loop:** [trial-budget.py](trial-budget.py) has a common in-memory clock and atomic reservations for one or two workers, fixed partitions, and a stop signal. [The pytest cases](../../../tests/test_trial_budget.py) reached exactly 12 model attempts and 24 tool attempts in each arm, covered concurrent admissions and refusal of the last contested slot, and verified inclusive token totals, unknown/over-bound usage, lost responses, and deadline/cancellation with accounted but discarded results. A second fixture used the same action loop for all arms: two independent contributors both started the same task; Nexus recorded `busy` for one contender, who then discovered and started the alternate task. Reads before start or outside the current task were refused. Reports over 2,048 UTF-8 bytes were refused. A simulated late ledger receipt stayed in the ledger audit but was excluded from review. Partial outputs survived a lost model response; unknown usage still makes the block unscored. The action loop is scripted, not a qualified provider adapter or an OS isolation test.

**Candidate tokenizer:** an existing CPU `llama-server` (`8f83d6c`, binary SHA-256 `7723f16ba1587cb6397d9ad8db71a1daf14cafde9dfedea2c9657958eb97134f`) loaded local Qwen2.5-Coder-1.5B-Instruct Q8_0 weights (GGUF SHA-256 `aa07e3c5ddab9e24821bebe5c5278bf565922166c4df15fa515faafb5243b699`) with `--offline --no-warmup --no-ui --no-context-shift --no-cache-prompt -c 8192 -np 2 -ngl 0`, in a fresh loopback-only network namespace. `/slots` reported two 4,096-token contexts. For each manifest-verified source, `POST /tokenize` with `add_special: true` and `parse_special: false` returned 4,217 tokens for `CONTRIBUTING.md` (18,189 bytes) and 26,035 for `docs/dev/BUILD.md` (111,073 bytes). These counts exclude any trial prompt. The loop therefore rehearses bounded 1-based inclusive reads (up to 128 lines and 8 KiB), with the same access rules in all arms. The [pinned upstream API notes](https://github.com/ggml-org/llama.cpp/blob/8f83d6c/tools/server/README.md#post-completion-given-a-prompt-it-returns-the-predicted-completion) warn that `n_predict` alone can overshoot at a partial multibyte character; [the pinned implementation](https://github.com/ggml-org/llama.cpp/blob/8f83d6c/tools/server/server-context.cpp#L1608-L1616) checks the slot context limit when shifting is off. The adapter reserves the whole slot rather than relying on an exact generated-token ceiling from `n_predict` alone.

**Candidate transport against an HTTP double:** the same [test module](../../../tests/test_trial_budget.py) exercised a local adapter that reserves the 4,096-token slot, then dispatches one integer-token prompt, one completion and no internal retry. Tokenization is a local, non-generating part of each measured attempt; a prompt that cannot fit is charged an attempt but not sent for completion. The wire fixture observed at most 12 completions for the solo arm and at most six per worker when concurrent. It returned missing/mismatched usage and observed no accepted action, and stalled midway through a response to exercise deadline and cancel with the server still blocked. A response delayed beyond the five-second connection timeout was still collected before the arm deadline. Known input/output totals are recorded separately; unknown attempts are not free or scorable.

**Real local engine smoke, not qualified:** [llama-smoke.py](llama-smoke.py) uses only synthetic text. Run `"$PYTHON" -I docs/nexus-pilot/rehearsals/llama-smoke.py 9182 complete` and repeat with `cancel` against a fresh disposable engine for each run. The engine ran in the loopback-only namespace with the flags above plus `--cache-ram 0 --host 127.0.0.1 --port 9182 -t 2`. Bubblewrap cleared the environment and exposed only the runtime libraries, engine, weights, minimal `/dev`, private `/proc` and temporary storage. No checkout, home, connector or credentials were mounted. Without constrained decoding, two synthetic requests each had **15 input + 12 output** tokens but did not produce parseable actions. A follow-up using the adapter's JSON-object constraint returned `{"op":"stop"}` from both slots, each with **21 input + 6 output** tokens, matching the engine logs. The constraint governs syntax, not authority or usefulness; the same dispatcher still checks action, fields and scope.

**Context boundary and interruption:** an oversized synthetic prompt was refused by the adapter before completion. A separate raw request with 4,096 input tokens was refused by the engine with HTTP 400; a 4,094-token request started processing but returned no final receipt before the experiment's 90 s timeout. This did not verify the near-boundary generation count. In the earlier unconstrained `cancel` run, the client returned in **17 ms**; the processing slot was not observed idle within **8 s**, and final usage was unknown. Disposable processes were stopped at teardown. A repeat using the same port immediately after teardown failed to bind; use a fresh network namespace per run. These observations do not demonstrate task quality, full per-worker isolation, or a clean stop with known usage. Do not use this transport for scored runs until those gaps are addressed.

**Synthetic contribution, first attempt:** a model received one invented task and a two-line fixture through the common loop. It tried to start an out-of-scope task, attempted a read without starting, and tried to submit without an active task. All three actions were refused and counted. It then stopped with no report: **4 model requests, 3 tool attempts, 938 known tokens, no unknown usage**. Parseable JSON was not enough to follow the task. Keep this zero-output observation separate from the frozen comparison, which was not run.

**Second attempt, same fixture and engine:** the prompt replaced placeholder IDs and paths with concrete examples and asked the model to stop on a refusal. The model skipped `start`, requested lines 3–4 of a two-line file, then repeatedly generated a malformed submission naming June 1 instead of Tuesday without reading the source. No report was accepted. Four completions finished (engine logs: **949 input + 112 output**); the process hit the probe's external 100 s timeout during the fifth, with no final receipt or arm summary. This is an incomplete, unscorable probe, not a fully metered zero-output run. Do not narrow allowed actions based on the expected correct answer to make the probe pass.

**Different local model, unchanged workflow probe:** swapped only the weights to `Ministral-3-3B-Instruct-2512-Q4_K_M.gguf` (SHA-256 `ee46f8f2cc4acf15e89699563e23b4a3919dce2e9ce7c44b53778d6590318e96`). Use the same isolated engine flags as above and run:

```sh
timeout 100 "$PYTHON" -I -u docs/nexus-pilot/rehearsals/llama-workflow.py \
  docs/nexus-pilot/rehearsals/trial-budget.py 9182
```

The [probe](llama-workflow.py) is the unchanged second-attempt fixture, including the prompt and assertions. It uses the solo runner's in-memory reservation, not a Nexus ledger. Ministral started `guide` and read lines 1–2 of `guide.md`. It then sent `{"op":"submit","filename":"guide.md","line":1,"finding":"The library opens on Tuesday."}` instead of the required `report` field. The dispatcher does not accept those fields, and the opening day is on line 2. No valid submission was observed. The three completed responses accounted for **679 input + 54 output** in the engine logs; the fourth started but the external 100 s timeout killed the probe (exit 124), without a final receipt or arm summary. This is progress through the read step, not a successful contribution or qualified comparison runner.

**Interruption with Ministral:** run `"$PYTHON" -I docs/nexus-pilot/rehearsals/llama-smoke.py 9182 cancel` and `late` against separate fresh isolated engines. Both probes attempted one completion and admitted no tool calls:

| Probe | Dispatcher observation | Engine observation |
| --- | --- | --- |
| `cancel`: interrupt while a slot is processing | Client returned in **17 ms**; no action or final receipt; **`unknown: 1`**, not zero consumption. Further tool admission was refused. | Slot was observed idle within 8 s. The log records **22 input + 4 output** after disconnection; it does not establish whether the backend cancelled or finished normally. |
| `late`: deliberately stop after receiving a real completion but before handing it to the gate | `{"op":"stop"}` was discarded with `cancelled`; **22 input + 6 output** retained, **`unknown: 0`**. Further tool admission was refused. | Final counts matched the engine log. This simulates late delivery at the dispatcher boundary; it is not a server-side cancellation test. |

The frozen tasks stayed unused. The next qualification probe should fix prompt framing as a separate, synthetic-only experiment, not weaken the action validator or score these observations as a contribution.

The runner returns known input/output totals and their cached/reasoning subsets for each worker, alongside counters, stops, traces and reports. Unknown attempts remain separate; in a two-worker rehearsal, losing one response does not erase already settled usage from the other worker.

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
