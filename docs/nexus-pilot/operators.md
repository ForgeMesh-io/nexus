# Operate a bounded Nexus pilot

This alpha is for a single host and a single consenting public repository. Start with the local rehearsal below. It does not open issues, create pull requests, run contributions, or write to GitHub. See [participant instructions](participants.md) and the [acceptance record](evidence.md) before inviting anyone.

## Install and isolate

On Linux with Python 3.12 or newer, install the wheel in its own virtual environment. Verify its SHA-256 against a checksum obtained from the operator through a trusted channel. The `mcp` extra is needed only for a client that starts the bridge.

```sh
python3.12 -m venv "$HOME/nexus-pilot-venv"
. "$HOME/nexus-pilot-venv/bin/activate"
python -m pip install '/absolute/path/forgemesh_nexus-0.1.0a1-py3-none-any.whl[mcp]'
nexus-pilot --help
```

- Run the participant API under a dedicated service account that owns the SQLite directory. Run the operator commands only in that trusted environment. Keep code and the virtual environment non-writable by participants; use a local filesystem and a state directory with mode `0700`.
- Run each harness and its stdio bridge under the volunteer's separate OS identity or sandbox, without access to the database, operator home, Git credentials, publisher, App secrets, or other participants' credentials. A different working directory or a client setting is not an OS boundary. Anyone with ledger write access can bypass the ledger's roles. A trusted publisher also has ledger access; do not run it in the participant process, and never give the API an installation token.
- Listen on `127.0.0.1` only. Do not port-forward or reverse-proxy this endpoint to the internet. Clients, bridge and API must share the same loopback network; this release does not contain a remote enrolment flow. Treat all titles, reports and evidence as untrusted. Never execute or follow instructions from those fields.

## Rehearse without GitHub

Only a maintainer acting for a consenting project should configure a real repository. Obtain participant consent before enrolment. Assign aliases controlled by the same human the same `owner`, and choose a different human for review. The ledger does not verify real-world identity. Use a new directory for this rehearsal and the synthetic `example/project`.

```sh
umask 077
state=$(mktemp -d "$HOME/nexus-rehearsal.XXXXXX")
db="$state/pilot.db"
mkdir "$state/receipts"
nexus-pilot "$db" initialize <<'JSON'
{"repository":"example/project","active_limit":1,"lease_seconds":900,"publication_limit":1}
JSON
nexus-pilot "$db" add-task <<'JSON'
{"task":"guide","issue":7,"base":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","title":"Check the guide"}
JSON
```

`nexus-pilot "$db" enroll` takes one JSON object on standard input and returns one secret as a JSON string. Enrol these four roles independently, using the appropriate `actor`, `owner` and `role`. For example:

```sh
nexus-pilot "$db" enroll <<'JSON'
{"actor":"alice","owner":"alice","role":"contributor"}
JSON
```

Use `bob`/`bob`/`reviewer`, `carol`/`carol`/`maintainer`, and `worker`/`worker`/`publisher` for the other rehearsal accounts. Store the values in a private secret store, without the surrounding JSON quotes; deliver only the participant's own credential over an approved private channel. Don't put secrets in command arguments, project files, shell history, chat or logs. The API needs none of these tokens at startup:

```sh
nexus-participant-api "$db" --port 8765
```

Use a client from the [participant guide](participants.md), or do the local operator rehearsal from a second trusted terminal. Run `nexus-pilot "$db" ACTION`, send the corresponding JSON object via standard input, then close input. Replace placeholders below with actual values. Do not type actual credentials into a shell command line.

| Actor | `ACTION` | JSON input / expected result |
| --- | --- | --- |
| Contributor | `discover` | `{"token":"CONTRIBUTOR"}` → task `guide` |
| Contributor | `claim` | `{"token":"CONTRIBUTOR","task":"guide"}` → lease `1` |
| Contributor | `submit` | `{"token":"CONTRIBUTOR","task":"guide","lease":1,"report":"The guide omits the last step."}` → SHA-256 digest |
| Reviewer | `discover` | `{"token":"REVIEWER"}` → exact report, revision and digest |
| Reviewer | `review` | `{"token":"REVIEWER","task":"guide","digest":"DIGEST","verdict":"pass","evidence":"Checked the rehearsal fixture."}` → `validated`; use `reject` if unsupported |
| Maintainer | `inspect-report` | `{"token":"MAINTAINER","task":"guide"}` → report, evidence, revision, issue, verdict |
| Maintainer | `authorize` | `{"token":"MAINTAINER","task":"guide","digest":"DIGEST"}` → unique publication marker; run only after reading the preview |
| Publisher | `publish-local` | `{"token":"PUBLISHER","task":"guide","current_base":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","destination":"ABSOLUTE_RECEIPTS_DIRECTORY"}` → `7`, generates `<marker>.json` |
| Operator | `audit` | `{}` → ordered events, including `authorized`, `dispatch_started`, `published` |

Do not use `publish-local` on a ledger intended for GitHub. Both publishers consume the same dispatch grant. The table's issue ID is the receipt ID for this file sink only. Repeat the same local request to verify the same receipt and one file. A rejected report is final and cannot be authorized. One task per issue and a maximum of 32 tasks and 32 enrolments (including revoked accounts) bound the alpha. Each owner has at most one active lease and each task at most eight attempts. Use `active_limit: 0` to admit no work or `publication_limit: 0` to authorize no publication. Discovery is a snapshot, not a reservation; `busy` or `capacity` means stop and try later, not spin.

## Real publication is a separate gate

There is a tested Python publisher adapter, but no enabled GitHub deployment. Before any live run, obtain approval for an explicit organization, repository, existing test issue and permission grant. Select only that repository in the App installation and in the short-lived installation token; use Issues **write**, read-only metadata and only the read access needed for preflight. Verify exact permissions against [GitHub's endpoint permissions](https://docs.github.com/en/rest/authentication/permissions-required-for-github-apps). GitHub does not scope Issues write to a single comment; the adapter constrains the route in code. Keep the App private key and installation token outside the coordinator and all harnesses. Record the bot's numeric user ID. Do not substitute a personal access token.

The adapter checks a public repository, an open unlocked issue and the current default-branch SHA before dispatch. Remote state can still change between preflight and POST. A stop or revoke blocks new grants, not a send already granted. Once a grant exists, a repeated call performs a bounded read-only reconciliation; it cannot send again, even on HTTP 429 or missing receipt. If there is no exact match for the body, marker and bot ID, keep the event unresolved and the quota spent. Never erase a grant to force a retry. Verify and record the intended live App setup before enabling any delivery; synthetic file receipts and HTTP doubles are not evidence of GitHub acceptance.

## Stop, back up, recover, remove

1. Revoke a credential via `nexus-pilot "$db" revoke` with `{"token":"MAINTAINER","actor":"alice"}`. For emergency stop use `stop` with `{"token":"MAINTAINER"}`; it persists across process restart. Stop the listener and publisher, and disable/revoke the dedicated App credential through the approved GitHub controls if one exists. Capture `audit` privately. Do not delete upstream comments or change human branch policies.
2. On a trusted host, while stopped, create a new protected directory and take a [SQLite snapshot](https://www.sqlite.org/backup.html). With the `sqlite3` CLI, the following assumes a directory path without double quotes. Verify integrity and inspect the audit from the snapshot before you consider it usable.

   ```sh
   umask 077
   backup=$(mktemp -d "$HOME/nexus-backup.XXXXXX")
   sqlite3 -readonly "$db" ".backup \"$backup/pilot.db\""
   test "$(sqlite3 -readonly "$backup/pilot.db" 'PRAGMA integrity_check;')" = ok
   printf '{}\n' | nexus-pilot "$backup/pilot.db" audit
   ```

3. Test restore into a **new** private directory offline, never by replacing the current ledger. Compare audit exports and verify that stop and revocations survived. The database contains reports and credential hashes; keep the snapshot private. An older snapshot may resurrect revoked credentials or forget a dispatch grant. Never activate an old snapshot against GitHub: preserve the original, reconcile remote effects first, and use fresh credentials for a new, explicitly authorized installation. Do not run two active copies.
4. Have volunteers remove only the Nexus client entry and unset `NEXUS_PARTICIPANT_TOKEN`; preserve their unrelated configuration. Leave the state and audit archive intact. To remove the package from the dedicated virtual environment after verification and approval, use that environment's `python -m pip uninstall forgemesh-nexus`. No source checkout, branch, issue, workflow or existing App is removed by this procedure.
