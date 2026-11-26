# Bounded Nexus pilot: acceptance record

**Status (2026-11-26): local alpha rehearsed; live acceptance and public release pending.** This slice adds local text reports without replacing the existing GitHub-native workflow. Code, tests and license are local; no App installation, GitHub write, or release was performed.

## What the evidence covers

| Requirement | Evidence and result | Boundary |
| --- | --- | --- |
| Opt-in and actual task scope | **Local observed:** initialization and enrolment are operator-only; no work before opt-in. Discovery returns a maintainer-selected existing-issue number and exact revision. [Ledger tests](../../tests/test_pilot.py). **Simulated:** the publisher refuses, without writing or spending the grant, when `.github/nexus.json` at the publication commit is missing, does not list the issue, does not cover a task path, or is malformed; restoring it lets the same authorization publish once ([ADR 002](adr-002-repository-consent.md), [publisher tests](../../tests/test_pilot_github.py)). | Consent is checked at publication, not at intake; not yet observed on GitHub (no consent file on the fork). Discovery does not scrape project needs. |
| One active lease per owner, expiration, bounded intake and zero agents | **Local observed:** concurrent attempts at the same task or last active slot; identity aliases; expired lease fencing; task, enrolment and attempt ceilings; zero-budget configuration. [Ledger](../../tests/test_pilot.py), [CLI](../../tests/test_pilot_cli.py). | Capacity is operator-set at initialization; no dynamic budget allocator. One task per issue and exact retries do not detect semantic duplicates across issues or outside Nexus. |
| Independent check and right to reject | **Local observed:** exact report digest, distinct enrolled owner, final review decision, maintainer preview and role-gated approval. [Ledger](../../tests/test_pilot.py), [CLI](../../tests/test_pilot_cli.py), [MCP](../../tests/test_pilot_mcp.py). | Human identities and evidence quality require independent human verification. No candidate code execution, PR, merge or automatic evaluation. |
| Separate identities, minimal authority and retirement | **Local observed:** four participant operations on loopback, no operator routes or GitHub token needed; invalid origins, headers and inputs refused. In an opt-in Bubblewrap test the bridge runs as UID/GID 65534, cannot see the ledger, and completes the MCP workflow. Revocation and emergency stop persist. [HTTP](../../tests/test_pilot_http.py), [MCP](../../tests/test_pilot_mcp.py), [CLI](../../tests/test_pilot_cli.py). | Sandbox evidence is for the bridge, not arbitrary harness processes or remote deployments. Host isolation still has to be configured. Nexus cannot revoke pre-existing, unrelated GitHub rights. |
| Backpressure, durability and audit | **Local observed:** with a slot occupied, 24 further claim requests across eight client workers receive `429 capacity`; the original lease and single claim audit event survive. Reports waiting for review or for the maintainer's decision hold their admission slot: new claims return `capacity` until a report is authorized, declined, rejected or withdrawn. A maintainer `decline` is final and idempotent, and a later `authorize` returns `not_validated`. Tests cover transaction rollback and restore into a new database with matching audit, revocation and stop. [HTTP](../../tests/test_pilot_http.py), [CLI](../../tests/test_pilot_cli.py), [ledger](../../tests/test_pilot.py). | Scripted contention, not a throughput or hostile-network benchmark. The local audit is not tamper-proof against an operator. Old backups must not resume remote publication. |
| Authorized publication and reconciliation | **Local observed:** the installed CLIs and bridge completed discovery → reservation → report → review → preview → approval → one file receipt; repeat returned the same receipt; audit, revoke and stop verified. **Simulated:** GitHub HTTP double checks one POST on the authorized issue, refuses stale revisions or ineligible issues, accepts a moved branch only when a complete compare shows no change in the task's paths, reconciles lost responses with body/marker/bot ID, and never retries an ambiguous POST after restart, 429, or restore of a SQLite backup taken after the send started (mutation check: with reconciliation disabled the test fails on `no_dispatch` instead of `uncertain_dispatch`, and still no second POST occurs because the restored ledger issues no new grant). [CLI](../../tests/test_pilot_cli.py), [publisher tests](../../tests/test_pilot_github.py), [ledger](../../tests/test_pilot.py). | **Not run on GitHub.** API preflight and POST are not atomic; stopping cannot recall a granted send. No verified App permission grant or live reconciliation. |
| Install, connect, apply client policies and remove | **Local observed:** wheel installed offline in a clean Python 3.12.9 environment; OpenCode v2.0.21 `/mcps` showed a connected server and an empty list after removing its config; in a full OpenCode agent turn driven by a scripted loopback OpenAI-compatible model, OpenCode called the real `nexus_discover` and `nexus_claim` tools (one `claimed` audit event), omitted `nexus_submit` from the model's tool list under a project `deny` rule, and refused the forced call with `No tool named "nexus_submit"` (no `submitted` event; removing the rule makes the test fail). The same turn passes with OpenCode's `remote` config against the loopback Streamable HTTP bridge, which forwards each caller's bearer token; an SDK client test shows that bridge rejecting a foreign `Host` (421) or `Origin` (403), refusing a missing or revoked token, and recording one claim; Codex CLI 0.172.0 performed real `discover`/`claim` calls via app-server, excluded and refused `submit`, refused discovery after revocation and listed no server after config removal. [Host tests](../../tests/test_pilot_hosts.py); [setup and prompt](participants.md). | The OpenCode turn uses a scripted model, not a real LLM: it proves host wiring and policy enforcement, not that a model chooses the right tools or writes a useful report. Codex was exercised without any model turn. Manual drafting is documented, not an integration. The HTTP bridge is loopback, unencrypted and without OAuth, so it is not a hosted or internet-facing MCP deployment. ChatGPT, a public HTTPS MCP endpoint and unassisted onboarding are **not run**; A2A is not implemented. |
| Preserve human work, detach without workflow migration | **Local observed:** existing policy configuration still checks, and no existing workflow, registry root, or license was changed. Read-only inventory and backups covered nine public Git mirrors, 62 remote branch/tag refs and paginated issues, PRs, comments and releases. | The mirrors and checked export checksums are not a complete GitHub restoration. They do not cover all local refs, uncommitted work or untracked files. Nothing was deleted. No production TUF ceremony or rollout was validated. |
| Positive net value at the same budget | **Not run.** [Registered comparison design](research.md#three-arm-experiment-not-run) sets up solo, independent and coordinated agents and measures unique accepted outcomes, time, spend, interruptions and active human minutes. | Fixture tests and published results on different workloads do not measure Nexus's value. There is no claim of less maintainer work or a faster review. |

## Reproduce the local checks

Use Linux, Python 3.12+, the optional MCP extra, and an environment with pytest. To reproduce all acceptance cases, also have `ip`, `unshare`, `bwrap`, `sqlite3`, `curl`, OpenCode and Codex. The `uv --offline` steps require the build environment and wheels already in the local cache. Use a disposable Linux VM instead if unprivileged user namespaces are disabled. Run with synthetic inputs; no GitHub or model credentials are used.

```sh
# From the pilot checkout; use a new parent directory and a Python environment with setuptools >=77.
repo=$PWD
scratch=$(mktemp -d)
uv build --wheel --offline --no-build-isolation --python "$BUILD_PYTHON" --out-dir "$scratch"
uv venv --offline --python 3.12 "$scratch/venv"
uv pip install --offline --python "$scratch/venv/bin/python" \
  "$scratch/forgemesh_nexus-0.1.0a1-py3-none-any.whl[mcp]" pytest
sha256sum "$scratch"/*.whl
cd "$scratch"
unshare --user --map-root-user --net bash -eu -c '
  ip link set lo up
  export NEXUS_TEST_HOSTS=1 NEXUS_TEST_BWRAP=1
  ./venv/bin/python -m pytest --import-mode=importlib -q -rs -p no:cacheprovider "$1/tests"
  ./venv/bin/python -I -m forgemesh check-config "$1"
' bash "$repo"
```

Observed from outside the checkout: **144 passed in 34.86 s**, `OK: swarm 'nexus', 8 task(s)`. SHA-256 of the tested `forgemesh_nexus-0.1.0a1-py3-none-any.whl`: `6286620d7e56c0b3dec0d1b8f4d30c1431030bfd181a03ad44f85396107e48e8`. This identifies the tested build, not a signed release or promise of byte-identical builds. See the [operator rehearsal](operators.md#rehearse-without-github) for the installed console commands and the [participant guide](participants.md) for the MCP steps.

For the historical check with a read-only mount and no network, use the pre-existing local test image:

```sh
docker run --rm --network none --read-only --tmpfs /tmp \
  -e PYTHONDONTWRITEBYTECODE=1 -v "$PWD:/src:ro" -w /src \
  sha256:d7f01b97472aec496d268246cc1376c4d2032b26288448b6a17c6b6b0409c255 \
  sh -ec 'python --version; python -m pytest -q -rs -p no:cacheprovider; python -m forgemesh check-config .'
```

Baseline `97fbb27bb683ee41f851390aa6bdfc1e4d6fa424`: **98 passed**, configuration OK. Candidate in the image (Python 3.12.16): **130 passed, 7 skipped in 18.50 s**, configuration OK. Skips: missing `mcp` (the whole MCP module counts as one skip), `sqlite3`, `curl`, and four opt-in host tests. The clean-wheel run covered those paths separately. These are local runs, not published attestations.

### OpenCode diagnostic limits

With a fresh home and project containing `mcp.servers.nexus`, `opencode api --standalone GET /api/config` saw the entry but `GET /api/mcp` returned an empty catalog and its connect route returned `MCP server not found: nexus`. The shared-service probe timed out waiting for startup. The standalone TUI is the proven path for connection and removal in this build; the automation initially misread ANSI repaint fragments rather than a failed connection. An earlier provider probe reported `provider.no-route` for a catalog `openai` override and a closed socket for a custom provider pointed at an unused port; a custom `@opencode/ai/providers/openai-compatible` provider pointed at a live loopback stub works. In this build `opencode run --standalone` reached the model but never started the configured MCP server (no `nexus_*` tool listed, no MCP log line), so the acceptance turn drives the standalone TUI with `--auto --prompt`. Do not generalize these observations beyond v2.0.21.

## Live gate (pending approval)

**Approved target (2026-11-26):** the maintainer approved a test on a fork of `ForgeMesh-io/anyps5`. The fork is `FRGMesh/anyps5` (public); issues were enabled on the fork only. Test issue [FRGMesh/anyps5#1](https://github.com/FRGMesh/anyps5/issues/1) asks for a plain-text documentation consistency check pinned to `8cfc7e611e0b0a2c22c6294a76c0fe7bbd8d506c`. A separate ledger (outside any checkout, mode `0700`) was initialized for that repository with `active_limit: 1` and `publication_limit: 1`. It holds the task `relinker-docs` and four distinct owners: an Antigravity/Gemini contributor, an OpenCode reviewer, the human maintainer and a publisher. Its audit so far: `initialized`, `task_added`, four `enrolled`. The private App `forgemesh-nexus-pilot-frgmesh` (ID 5940524, bot user ID 361657239) was created from a manifest with Issues write, Contents read and Metadata read, and no webhook. Its private key is kept outside the ledger and every harness. A JWT check found **no installation yet**, and nothing has been published. The operator command `publish-github` takes the installation token from `NEXUS_GITHUB_TOKEN` only; an HTTP-double test checks that a missing token is refused, extra fields are rejected, one POST is made over two calls, and the token is never printed.

**Antigravity (Gemini) attempt:** `agentapi` needs `ANTIGRAVITY_LS_ADDRESS` and `ANTIGRAVITY_CSRF_TOKEN`; it failed without them. Using the running hub's address and token file, a new conversation (Antigravity 2.35.2) answered `NO_NEXUS_TOOLS`. Its metadata showed `launchedMcpServers: []` although `~/.gemini/config/mcp_config.json` now declares a stdio `nexus` server. The same server entry listed four tools and returned `relinker-docs` through an MCP SDK client. Likely cause, not verified: the app was already running when the file was written. Next check: restart Antigravity by hand and confirm the server under **MCP Servers** before rerunning the turn. After the app restarted, a second probe listed `discover` and `claim` under `nexus` (the conversation metadata still shows `launchedMcpServers: []`, so that field is not a reliable signal).

**Real agent contribution (observed, 2026-11-26):** an Antigravity 2.35.2 agent running `gemini-4-hydrogen-tiered-high` ("Gemini 4 Hydrogen (High)", read from the conversation's generation metadata) received the [participant prompt](participants.md), driven through `agentapi`. It then:

1. Called the real `nexus.discover` tool, which returned the `relinker-docs` task.
2. Showed the issue, the pinned commit and the task, and asked permission before reserving. Once authorized, it called `claim` (`lease: 1`).
3. Read only the two authorized raw files at the pinned revision. Its first `curl` failed in Antigravity's network sandbox, so it re-ran the command under the host's auto-approval policy.
4. Showed a 1,483-character report and waited for approval before calling `submit` (digest `c6d54c82…43a9`).

The audit gained exactly `claimed` and `submitted`, both by actor `gemini`.

An independent reviewer (a different owner, OpenCode/Claude) fetched both files at the pinned commit and matched all 8 quoted strings verbatim. It recorded `pass` with these caveats: the `--parallel` difference is cosmetic under Ninja, and the report missed the Python 3.9/3.11 minimums. The ledger answered `validated`. The maintainer preview shows author `gemini`, reviewer `claude` and verdict `pass`.

**Codex against the live ledger (observed, 2026-11-26):** the user's real `~/.codex/config.toml` (Codex CLI 0.172.0) was backed up. A `nexus` entry was then appended, with `enabled_tools = ['discover']`, a separately enrolled contributor `codex` (owner `codex-gpt`), and the token read from a 0600 file by `/bin/sh -c`. Through `codex app-server` the following was observed:

1. `mcpServerStatus/list` listed only `discover`.
2. `discover` returned `{"repository": "frgmesh/anyps5", "tasks": []}`. The only task was already submitted by `gemini`, so a second contributor is not offered duplicate work.
3. A forced `submit` call was refused by Codex itself: `tool 'submit' is disabled for MCP server 'nexus'`.
4. After the maintainer ran `revoke`, `discover` returned `unauthorized`.
5. Restoring the backup made the config byte-identical to the original (`cmp`), and `codex mcp list` no longer showed `nexus`.

The audit gained only `enrolled` (codex) and `revoked` (mathis). A real Codex model turn could not run because the local ChatGPT login has expired (`refresh token has expired`); Codex therefore still has **no observed model-driven call**.

The "participant" answers in the Antigravity chat were typed by the operator agent, so this run does not measure a non-technical person's experience.

Obtain explicit approval for one public repository, one existing test issue, one comment and the repository-scoped App permissions. Confirm consent, snapshot the pinned default-branch revision, and use a separate disposable pilot ledger. Record the preflight, one bot-authored receipt verified by an independent read, the read-only retry/reconciliation outcome, a stale/withdrawn refusal, and final stop and credential removal. No cleanup by deletion is implied. Do not expose the loopback participant API remotely to run this gate. Judge whether to broaden the deployment only after actual client onboarding, maintainer feedback and the budget-matched comparison.
