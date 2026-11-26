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

## Unassisted volunteer trial (not run)

Use a fresh volunteer and a practice task that cannot publish. Before the trial, the operator prepares the local service, provides the verified wheel or installed bridge and port, and delivers the participant credential privately. Record whether the participant received an installed bridge or installed it themselves; do not combine the two cases. Give the volunteer only the [participant guide](../participants.md) and the invitation. With consent, observe without coaching and record time to first authenticated discovery, first submission and successful detachment, plus the exact step for any blockage or help request. Stop if the participant is asked to paste a credential or is offered real write access. Verify the submission and revocation in the audit. Record operator preparation and review time separately; the rehearsal above provides no human timing or success rate.

**Separate manual fallback (not run):** in a fresh chat with no Nexus connector or GitHub write access, give the volunteer the same invitation and a public issue, pinned revision and relevant excerpts. Do not give them the connector credential. Observe whether the chat explains that it cannot connect, asks for missing evidence and offers only an editable draft for human review. The chat must not say it reserved, submitted or validated work or post the draft. Compare the ledger audit before and after; the manual attempt must add no events. Record pass, unsafe behavior or blockage separately from connected onboarding. No successful fallback is implied by a successful connector test.
