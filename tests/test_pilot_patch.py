import io
import json
import shutil
import subprocess
import sys

import pytest

from forgemesh.pilot import Pilot, PilotError


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout


@pytest.fixture
def project(tmp_path):
    repo = tmp_path / "project"
    (repo / "docs").mkdir(parents=True)
    (repo / "src").mkdir()
    (repo / "docs" / "guide.md").write_text("# Guide\n\nStep one.\n")
    (repo / "src" / "main.c").write_text("int main(void) { return 0; }\n")
    git(tmp_path, "init", "-q", str(repo))
    git(repo, "add", ".")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qm", "base")
    return repo, git(repo, "rev-parse", "HEAD").strip()


def diff(repo, change):
    change(repo)
    patch = git(repo, "diff", "--no-color")
    git(repo, "reset", "-q")
    git(repo, "checkout", "-q", ".")
    git(repo, "clean", "-fdq")
    return patch


DOCS = lambda repo: (repo / "docs" / "guide.md").write_text("# Guide\n\nStep one.\nStep two.\n")
SRC = lambda repo: (repo / "src" / "main.c").write_text("int main(void) { return 1; }\n")


def NEW(repo):
    (repo / "docs" / "new.md").write_text("New\n")
    git(repo, "add", "-N", ".")


@pytest.fixture
def ledger(tmp_path, project):
    _, base = project
    ledger = Pilot(tmp_path / "pilot.db")
    ledger.initialize("example/project", active_limit=1)
    tokens = {
        "writer": ledger.enroll("writer", "alice", "contributor"),
        "reviewer": ledger.enroll("reviewer", "bob", "reviewer"),
        "maintainer": ledger.enroll("maintainer", "carol", "maintainer"),
    }
    ledger.add_task("fix", 7, base, "Fix the guide", ["docs/"], kind="patch")
    return ledger, tokens


def submit(ledger, tokens, patch):
    return ledger.submit(tokens["writer"], "fix", ledger.claim(tokens["writer"], "fix"), patch)


def test_patch_tasks_need_paths_and_a_known_kind(ledger):
    ledger, tokens = ledger
    with pytest.raises(PilotError, match="invalid_input"):
        ledger.add_task("nopaths", 8, "b" * 40, "No paths", kind="patch")
    with pytest.raises(PilotError, match="invalid_input"):
        ledger.add_task("odd", 9, "b" * 40, "Odd", ["docs/"], kind="pull_request")
    assert [(t["id"], t["kind"]) for t in ledger.discover(tokens["writer"])["tasks"]] == [("fix", "patch")]


def test_unchecked_patch_is_hidden_from_review_and_holds_its_slot(ledger, project):
    ledger, tokens = ledger
    repo, _ = project
    digest = submit(ledger, tokens, diff(repo, DOCS))
    assert ledger.discover(tokens["reviewer"])["tasks"] == []
    with pytest.raises(PilotError, match="not_checked"):
        ledger.review(tokens["reviewer"], "fix", digest, "pass", "Looks right")
    ledger.add_task("other", 8, "b" * 40, "Other")
    other = ledger.enroll("other", "dana", "contributor")
    with pytest.raises(PilotError, match="capacity"):
        ledger.claim(other, "other")


def test_failed_check_is_a_final_rejection_that_releases_the_slot(ledger, project):
    ledger, tokens = ledger
    repo, _ = project
    digest = submit(ledger, tokens, diff(repo, SRC))
    ledger.record_check("fix", digest, reason="out_of_scope")
    ledger.record_check("fix", digest, reason="out_of_scope")
    assert ledger.inspect_report(tokens["maintainer"], "fix")["verdict"] == "reject"
    with pytest.raises(PilotError, match="conflict"):
        ledger.record_check("fix", digest, files=["docs/guide.md"])
    ledger.add_task("other", 8, "b" * 40, "Other")
    assert ledger.claim(ledger.enroll("other", "dana", "contributor"), "other") == 1
    assert [e["details"].get("result") for e in ledger.audit() if e["event"] == "checked"] == ["out_of_scope"]


def test_checked_patch_reaches_the_reviewer_with_its_files(ledger, project):
    ledger, tokens = ledger
    repo, _ = project
    patch = diff(repo, DOCS)
    digest = submit(ledger, tokens, patch)
    with pytest.raises(PilotError, match="stale_digest"):
        ledger.record_check("fix", "0" * 64, files=["docs/guide.md"])
    ledger.record_check("fix", digest, files=["docs/guide.md"])
    [task] = ledger.discover(tokens["reviewer"])["tasks"]
    assert (task["kind"], task["report"], task["checked"]) == ("patch", patch, ["docs/guide.md"])
    assert ledger.review(tokens["reviewer"], "fix", digest, "pass", "Applied and read") == "validated"


def test_patch_size_limit_is_larger_than_reports_but_bounded(ledger):
    ledger, tokens = ledger
    lease = ledger.claim(tokens["writer"], "fix")
    with pytest.raises(PilotError, match="invalid_input"):
        ledger.submit(tokens["writer"], "fix", lease, "x" * 16_385)
    assert len(ledger.submit(tokens["writer"], "fix", lease, "x" * 16_384)) == 64


def _bwrap_works():
    if not shutil.which("bwrap"):
        return False
    from forgemesh.pilot_patch import sandboxed

    try:
        return sandboxed(["/usr/bin/true"]).returncode == 0
    except PilotError:
        return False


SANDBOX = pytest.mark.skipif(not _bwrap_works(), reason="needs a working bubblewrap")


@SANDBOX
def test_sandbox_has_no_network_no_home_and_a_private_tmp(tmp_path):
    from forgemesh.pilot_patch import sandboxed

    probe = ("import os, socket, sys\n"
             "try:\n    socket.create_connection(('1.1.1.1', 53), 2); print('net')\n"
             "except OSError: print('no-net')\n"
             "print('home' if os.path.exists(sys.argv[1]) else 'no-home')\n"
             "print(sorted(os.listdir('/tmp')))\n")
    result = sandboxed(["/usr/bin/python3", "-c", probe, str(tmp_path)])
    assert result.stdout.decode().split("\n")[:3] == ["no-net", "no-home", "[]"]


@SANDBOX
@pytest.mark.parametrize("make,result", [
    (lambda repo: diff(repo, DOCS), {"ok": True, "files": ["docs/guide.md"]}),
    (lambda repo: diff(repo, NEW), {"ok": True, "files": ["docs/new.md"]}),
    (lambda repo: diff(repo, SRC), {"ok": False, "reason": "out_of_scope"}),
    (lambda repo: diff(repo, DOCS) + diff(repo, SRC), {"ok": False, "reason": "out_of_scope"}),
    (lambda repo: diff(repo, DOCS).replace("Step one.\n", "Step zero.\n", 1), {"ok": False, "reason": "does_not_apply"}),
    (lambda repo: diff(repo, DOCS).replace("docs/guide.md", "../outside.md"), {"ok": False, "reason": "forbidden_change"}),
    (lambda repo: diff(repo, DOCS).replace("docs/guide.md", ".git/config"), {"ok": False, "reason": "forbidden_change"}),
    (lambda repo: "diff --git a/docs/l b/docs/l\nnew file mode 120000\n--- /dev/null\n+++ b/docs/l\n@@ -0,0 +1 @@\n+/etc/passwd\n\\ No newline at end of file\n",
     {"ok": False, "reason": "forbidden_change"}),
    (lambda repo: "diff --git a/docs/guide.md b/docs/moved.md\nsimilarity index 100%\nrename from docs/guide.md\nrename to docs/moved.md\n",
     {"ok": False, "reason": "forbidden_change"}),
    (lambda repo: "diff --git a/docs/guide.md b/docs/guide.md\nold mode 100644\nnew mode 100755\n",
     {"ok": False, "reason": "forbidden_change"}),
    (lambda repo: "diff --git a/docs/x.bin b/docs/x.bin\nnew file mode 100644\nGIT binary patch\nliteral 1\nIcmZpX0000F00031\n\nliteral 0\nHcmV?d00001\n\n",
     {"ok": False, "reason": "forbidden_change"}),
    (lambda repo: "not a patch\n", {"ok": False, "reason": "does_not_apply"}),
])
def test_patch_is_applied_at_the_pinned_commit_and_kept_in_scope(project, make, result):
    from forgemesh.pilot_patch import check_patch

    repo, base = project
    patch = make(repo)
    # A later commit on the mirror must not change the verdict for the pinned base.
    (repo / "docs" / "guide.md").write_text("Rewritten after the base.\n")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qam", "later")
    assert check_patch(repo, base, ["docs/"], patch) == result
    assert git(repo, "status", "--porcelain") == ""


@SANDBOX
def test_operator_cli_checks_and_records_the_verdict(ledger, project, tmp_path, monkeypatch, capsys):
    from forgemesh import pilot_cli

    ledger, tokens = ledger
    repo, _ = project
    digest = submit(ledger, tokens, diff(repo, DOCS))

    def run(**payload):
        monkeypatch.setattr(sys, "argv", ["nexus-pilot", str(ledger.path), "check-patch"])
        monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(json.dumps(payload).encode())))
        code = pilot_cli.main()
        return code, json.loads(capsys.readouterr().out)

    assert run(task="fix", repository="relative/path") == (1, {"error": "invalid_input"})
    assert run(task="fix", repository=str(repo)) == (0, {"ok": True, "files": ["docs/guide.md"]})
    assert run(task="fix", repository=str(repo)) == (0, {"ok": True, "files": ["docs/guide.md"]})
    assert [t["id"] for t in ledger.discover(tokens["reviewer"])["tasks"]] == ["fix"]
    assert ledger.inspect_report(tokens["maintainer"], "fix")["digest"] == digest


def test_validated_patch_is_published_as_a_comment_through_the_same_gateway(ledger, project):
    from forgemesh.pilot_github import GitHubPublisher

    ledger, tokens = ledger
    repo, _ = project
    patch = diff(repo, DOCS)
    digest = submit(ledger, tokens, patch)
    ledger.record_check("fix", digest, files=["docs/guide.md"])
    ledger.review(tokens["reviewer"], "fix", digest, "pass", "Applied and read")
    ledger.authorize(tokens["maintainer"], "fix", digest)
    publisher = ledger.enroll("publisher", "worker", "publisher")
    intent = ledger.begin_dispatch(publisher, "fix", ledger.pending_target(publisher, "fix")["base"])
    body = GitHubPublisher._body(intent)
    assert intent["kind"] == "patch"
    assert "Nexus patch for" in body and "git apply" in body
    # Indented code block: the diff cannot close a fence or inject markup.
    assert "\n    diff --git a/docs/guide.md b/docs/guide.md\n" in body
    assert "```" not in body
