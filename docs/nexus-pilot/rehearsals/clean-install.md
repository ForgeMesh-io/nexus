# Clean install, connect, and leave

**Local observed, 2026-11-26.** Linux, CPython 3.12.9, uv 0.13.9 and OpenCode 2.0.21. The Python interpreter, OpenCode and wheel were already available. The virtual environment, home, project and ledger were new. The test used a synthetic task on `example/project` with `publication_limit: 0`. After installation, only loopback was available. No model call, GitHub credential, live repository or existing profile was used. This was automated, not a study with a volunteer or a test of OS-account isolation.

## Replay

1. Verify the wheel before installing: `forgemesh_nexus-0.1.0a1-py3-none-any.whl`, SHA-256 `522e52d4a49694faaf4751f7daaa295dfad8d8c416b574df23ac61520bd73151`. Start in a new Linux profile or a disposable environment. The tested installation used a new `HOME` and empty `UV_CACHE_DIR`:

   ```sh
   uv venv --offline --python "$PYTHON312" "$VENV"
   uv --no-config pip install --default-index https://pypi.org/simple \
     --python "$VENV/bin/python" "$WHEEL[mcp]"
   uv pip check --python "$VENV/bin/python"
   ```

   `PYTHON312`, `VENV` and `WHEEL` are absolute paths to the local interpreter, the new virtual environment and the verified wheel. `--offline` on `uv venv` avoids fetching Python; installing dependencies uses the public index.
2. Follow the [operator rehearsal](../operators.md#rehearse-without-github) with the installed CLI, keeping `publication_limit: 0`. Add `guide`, enrol a contributor and a maintainer, then start the installed participant API. `--port 0` lets Linux choose a free port; use the port printed by the API. Run the [OpenCode setup](../participants.md#local-setup-reference-for-the-operator) from a new project with the installed `nexus-participant-mcp` path and the contributor credential in the launching process. In `opencode --standalone`, open `/mcps` and verify that `nexus` is connected.
3. Make an authenticated `discover`; the result should name `guide`, issue #7 and the pinned revision. This run used the installed MCP SDK to call `discover` through the same bridge command instead of asking OpenCode to run a model. For a no-provider repeat of that probe, the [stdio MCP test](../../../tests/test_pilot_mcp.py) exercises the same request and checks the exact result.
4. Revoke the contributor and repeat `discover` before changing the client configuration: it should return `unauthorized`. Remove only the Nexus entry, close the dedicated client and unset the credential. In a fresh `opencode --standalone`, `/mcps` should no longer list Nexus. Stop the rehearsal ledger and listener. Uninstall **only** Nexus from the dedicated environment with `uv pip uninstall --offline --python "$VENV/bin/python" forgemesh-nexus`. Verify that all three installed entry points are gone and the retained database still passes `PRAGMA integrity_check`.

## Observed checks and friction

```text
Checked 32 packages
All installed packages are compatible
Bridge startup without credential: exit 2
OpenCode /mcps: nexus connected
MCP discover: guide, issue #7, exact pinned revision
MCP discover: unauthorized
OpenCode /mcps after removing only nexus: No items available
Audit: initialized, task_added, enrolled, enrolled, revoked, stopped
Package entry points absent; retained ledger integrity: ok
```

- With network disabled and an empty cache, the same wheel failed to install because `mcp` was not cached. With cached dependencies the offline installation also worked. Obtain dependencies before handing an offline participant the wheel.
- OpenCode 2.0.21 rejected `opencode mcp list --standalone` (`Unrecognized flag: --standalone`). Use `opencode --standalone`, then `/mcps`. A visible connection is not an authenticated task call. The rehearsal restored the original project config byte-for-byte.
- A missing credential stops the bridge; a revoked credential can still allow MCP negotiation but cannot discover a task. Preparing the API, connector configuration and private credential delivery still takes an operator. The chat prompt does not perform setup.

## Offline wheelhouse (2026-11-27)

An operator can supply the checked `forgemesh-nexus-0.1.0a1-linux-x86_64-cp312-wheelhouse.tar.gz` candidate. This is not a public release or a signed artifact. Verify the expected archive hash through a trusted channel before extracting into a new private directory. The bundle contains `BUILD-REF` and 32 wheels with individual SHA-256 checksums in `wheelhouse/SHA256SUMS`. It contains no credentials, pilot database, Python interpreter, AI harness or test packages. Tested on Linux x86-64 with CPython 3.12.9 and glibc 2.44; some wheels require glibc 2.34 or newer. No other platform was tested with this bundle.

```sh
# BUNDLE is the absolute path to the archive supplied by the operator.
umask 077
scratch=$(mktemp -d)
printf '%s  %s\n' 8e65106da041e16641f6e9a67e8fe7f90b40e6eab7891a0b52831d588fa977eb "$BUNDLE" | sha256sum -c - &&
  tar --no-same-owner -xzf "$BUNDLE" -C "$scratch" &&
  (cd "$scratch/wheelhouse" && sha256sum -c SHA256SUMS) &&
  python3.12 -I -m venv "$scratch/venv" &&
  PIP_CONFIG_FILE=/dev/null "$scratch/venv/bin/python" -I -m pip --isolated --disable-pip-version-check --no-cache-dir install \
    --no-index --only-binary=:all: --find-links "$scratch/wheelhouse" 'forgemesh-nexus[mcp]==0.1.0a1' &&
  "$scratch/venv/bin/python" -I -m pip check &&
  "$scratch/venv/bin/nexus-pilot" --help
```

**Build provenance:** `2010c8b80bfb172d0fc7dfac58113e478c0be4a2`, setuptools 84.2.1, Python 3.12.9. Build from a fresh `git archive` of that commit with `umask 077`, `SOURCE_DATE_EPOCH` set to the commit timestamp, and `uv build --wheel --offline --no-build-isolation --python "$BUILD_PYTHON"`. Two fresh builds with those inputs produced the same wheel SHA-256, `0f533c2a495b061c3452a0cb9ad2e58105b1eeca506fc39d74ab027a71be8611`. A different umask changed ZIP permission metadata and the digest. [Download binary dependencies](https://pip.pypa.io/en/stable/cli/pip_download/) from the public index on a matching platform and retain and verify the wheelhouse manifest; a later dependency resolution is not guaranteed to reproduce the bundle.

**Observed:** With a fresh home and virtual environment, cache disabled, and only loopback networking, the install succeeded and `pip check` found no broken requirements. All three console commands started. The exact archive-install commands above also passed in a second fresh environment and refused a modified archive before extraction. With separate local pytest wheels, the installed package passed **240 tests in 43.56 s** with the OpenCode, Codex and Bubblewrap checks enabled; `check-config` returned `OK: swarm 'nexus', 8 task(s)`. No model provider or GitHub credential was used. Offline installation does not imply that Antigravity can run its cloud model offline.

**Operational restore rehearsal:** using the installed console commands and a scripted MCP client, a fresh synthetic ledger with `publication_limit: 0` completed discovery, reservation and submission with the exact report digest. After `stop`, discovery returned `stopped`; the contributor was then revoked and the listener stopped. The [operator's SQLite backup procedure](../operators.md#stop-back-up-recover-remove) was tested by restoring into a second private directory, offline. Both snapshots returned `integrity_check: ok`; the audit was identical, the contributor got `unauthorized`, and the maintainer still got `stopped`. No publisher was enrolled and the publication table remained empty. Audit: `initialized`, `task_added`, `enrolled`, `enrolled`, `claimed`, `submitted`, `stopped`, `revoked`. This does not test restoring a live publication or running an actual Antigravity session.

## Public copy-paste path in Antigravity (simulated, 2026-11-28)

**Simulated participant, live public infrastructure.** The maintainer approved using the `development` registry and the pinned verifier for this trial, with no GitHub writes. The operator agent typed the participant's replies, so this does not measure a non-technical person's experience.

- **Prompt:** generated by the served portal script (`app.js` SHA-256 `8d00546033ee986fd9cabf7868a7f1f0b3d9f9aeeb5ba61e5e971956037221c8`, `data/portal.json` generated `2026-11-28T04:25:50Z`) for the NEXUS card. Pasted byte for byte (SHA-256 `a2707a20d9727b5e56d66cccd74df217fe48f454cced46bb9c52400ea2aa036a`) into a new Antigravity 2.35.2 conversation (`1bfbf328-…`) through `agentapi`, with no MCP server configured.
- **Turn 1 (at most 134 s, from send to the polled answer):** the agent downloaded `1.root.json`, matched the anchor with `sha256sum`, cross-checked the registry README, read `environment: development`, and stopped to ask for consent before cloning or installing anything.
- **Simulated reply:** consent to the development registry and the verifier, 15 minutes, no execution, no claim or publication; "recommend a task and stop".
- **Turn 2 (at most 191 s):** the agent cloned at the pin `0f2c777`, created a venv with the host's Python 3.14.10 (JOIN asks for 3.12; no other interpreter was installed), installed the hash-locked dependencies and ran `forgemesh verify`, which succeeded. It switched to the manifest's `nexus_ref`, read the policy and live state, recommended `NX-0006` and stopped. No issue, comment, PR or claim was created after the run started (checked with the GitHub API).
- **Operator check:** re-running the verifier at `0f2c777` returned the same manifest. Its `nexus_ref` `8f0500e` is an ancestor of the verifier pin, and at that ref `NX-0006` declares `execution: container` and the CLI lacks `--no-execution`. A participant who follows step 2 literally therefore gets an older CLI and an outdated view of the onboarding task. JOIN's fallback ("if your verified CLI predates that flag") covers this, but the signed manifest lags the published pin. Fixing it requires re-signing and redeploying the registry, which has not been authorised.

The result shows that the copy-paste path works in one real harness as far as verified recommendation, with human consent gates in the right places. It does not cover a claim, contribution or publication through the public path, other harnesses, or self-installation by a non-technical person.

## Unassisted volunteer trial (not run)

**Deferred by the maintainer on 2026-11-29** in favour of checking the public copy-paste path in a real harness. Agent-simulated runs may be timed, but they are reported as simulations, not as this trial.

Before starting either path, confirm which non-technical volunteer explicitly consented to being observed in both sessions. They may stop at any time. Observe without coaching and note the step of any blockage or help request. Stop if the volunteer is asked to paste a credential or is offered real write access. **Do not time the participant by default.** Only with separate explicit consent to timing, measure elapsed time from the start of the participant's turn, after preparation, to the applicable milestones (authenticated discovery, submission and exit for the connected path; draft and exit for the manual path). Without timing consent, record only whether the milestones were reached; do not infer participant durations from logs. Keep any operator preparation and review times separate.

**Shared practice fixture:** use `example/project`, task `guide` (`Check whether the kit pickup instructions agree`), fictional issue `#7`, revision `bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb` and the numbered `docs/guide.md` excerpt below for both paths. Give the volunteer the [participant guide](../participants.md), the invitation and this fixture. All project material is supplied in the invitation; no GitHub lookup, project command or fetch is needed. Use a separate fresh local ledger for each path, each with `publication_limit: 0`, no publisher and no GitHub credentials. Neither path publishes anything.

```text
docs/guide.md
1: Kit pickup begins at 09:00 on Saturday.
2: Collect your kit at the library's west entrance.
3: The pickup checklist directs volunteers to the east entrance.
```

**Antigravity with a prepared connector:** before observation, start the local service for the connected ledger, enrol only a contributor and a maintainer, and configure the verified bridge in a dedicated profile. Keep the credential in the launching process; never put it in the invitation or chat. Use a fresh port and credential. Stop on missing tools rather than switching harnesses; record any restart or configuration edit during observation as assistance. After the volunteer exits or asks to stop, revoke the contributor, remove only the practice connector, and check that the retired credential is refused. Record the discovered task and revision, report digest if submitted, and whether the audit shows one `claimed`, one `submitted`, one contributor revocation and no publication grant. Operator cleanup is separate from participant work. This path measures use with a prepared connector; self-installation is a separate trial.

**Manual fallback:** use a fresh chat with no Nexus connector, participant credential or GitHub write access. Supply the same fictional fixture. Add this instruction to the practice invitation: “Show me an editable draft in this chat for me to read, then stop. Do not send it anywhere.” Observe whether the chat explains that it cannot connect and offers only the draft, without claiming a reservation, submission or validation. Compare the manual ledger's audit before and after; it must be unchanged.

**Record separately for each path:** observation consent, timing consent, milestones reached, exit or withdrawal, help requested, assistance, and any blockage or unsafe behavior. A supported report identifies the contradiction between lines 2 and 3 without guessing which entrance is correct. Neither human observation has been run.
