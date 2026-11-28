"""Kill an installed pilot writer before commit and recover its hot journal offline."""

from contextlib import closing
from functools import partial
from hashlib import sha256
import json
from pathlib import Path
from select import select
import signal
import sqlite3
import subprocess
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch

from forgemesh.pilot import Pilot


PYTHON = [sys.executable, "-I", "-B"]
HOT_HEADER = bytes.fromhex("d9d505f920a163d7")
connect = sqlite3.connect


class InterruptedConnection(sqlite3.Connection):
    def execute(self, sql, parameters=()):
        if sql == "BEGIN IMMEDIATE":
            # Force dirty pages out before commit so recovery must use the journal.
            super().execute("PRAGMA cache_size=1")
            super().execute("PRAGMA cache_spill=ON")
        return super().execute(sql, parameters)

    def __exit__(self, exc_type, exc, traceback):
        if exc_type is None:
            assert self.in_transaction
            print("revocation written; before commit", flush=True)
            signal.pause()
            raise AssertionError("Expected SIGKILL")
        return super().__exit__(exc_type, exc, traceback)


def interrupt(path, token):
    command = [*PYTHON, str(Path(__file__).resolve()), "--writer", str(path)]
    with subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE) as child:
        try:
            child.stdin.write(token.encode())
            child.stdin.close()
            ready, _, _ = select([child.stdout], [], [], 15)
            assert ready and child.stdout.readline() == b"revocation written; before commit\n"
        finally:
            if child.poll() is None:
                child.kill()
            child.wait(timeout=5)
        assert child.returncode == -signal.SIGKILL


def cli(path, action, *, token=None):
    payload = {} if token is None else {"token": token}
    result = subprocess.run([*PYTHON, "-m", "forgemesh.pilot_cli", str(path), action],
                            input=json.dumps(payload), capture_output=True, text=True, timeout=10)
    return result.returncode, result.stdout


def rehearse(path):
    ledger = Pilot(path)
    ledger.initialize("example/project", publication_limit=0)
    maintainer = ledger.enroll("maintainer", "maintainer", "maintainer")
    previous = ledger.enroll("previous", "previous", "contributor")
    pending = ledger.enroll("pending", "pending", "contributor")
    ledger.add_task("guide", 7, "b" * 40, "Synthetic task")
    lease = ledger.claim(pending, "guide")
    assert lease == 1
    ledger.revoke(maintainer, "previous")
    ledger.stop(maintainer)

    before = path.read_bytes()
    journal = path.with_name(path.name + "-journal")
    assert not journal.exists()
    code, audit = cli(path, "audit")
    assert code == 0
    claimed, revoked, stopped = json.loads(audit)[-3:]
    assert [row["event"] for row in (claimed, revoked, stopped)] == ["claimed", "revoked", "stopped"]
    expires = claimed["details"]["expires"]

    interrupt(path, maintainer)
    dirty = path.read_bytes()
    journal_size = journal.stat().st_size
    assert dirty != before and journal_size > 512 and journal.read_bytes().startswith(HOT_HEADER)
    print(f"SIGKILL confirmed; main file changed; rollback journal header valid ({journal_size} bytes)")

    code, refusal = cli(path, "audit")
    assert (code, json.loads(refusal)) == (1, {"error": "storage_unavailable"})
    assert path.read_bytes() == dirty and journal.exists()
    print("First read-only CLI audit: storage_unavailable; recovery journal retained")

    with closing(connect(f"{path.as_uri()}?mode=rw", uri=True)) as db:
        assert db.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        assert db.execute("PRAGMA journal_mode").fetchone() == ("delete",)
        assert db.execute("SELECT stopped, publication_limit FROM settings").fetchone() == (1, 0)
        assert db.execute("SELECT id, revoked FROM actors ORDER BY id").fetchall() == [
            ("maintainer", 0), ("pending", 0), ("previous", 1),
        ]
        assert db.execute("SELECT actor, attempt, expires FROM tasks WHERE id='guide'").fetchone() == (
            "pending", lease, expires,
        )
        assert db.execute("SELECT count(*) FROM publications").fetchone() == (0,)
    assert not journal.exists() and path.read_bytes() == before
    assert cli(path, "audit") == (0, audit)
    for token, expected in ((previous, "unauthorized"), (pending, "stopped")):
        code, refusal = cli(path, "discover", token=token)
        assert (code, json.loads(refusal)) == (1, {"error": expected})
        print(f"Post-recovery CLI discover: {expected}")
    print("PASS: journal removed by SQLite; integrity ok; no foreign-key errors; "
          "exact database and audit; previous revocation and lease preserved; 0 publications")
    print(f"Pre-crash and recovered database SHA-256: {sha256(before).hexdigest()}")


if __name__ == "__main__":
    if sys.argv[1] == "--writer":
        with patch("forgemesh.pilot.sqlite3.connect", partial(connect, factory=InterruptedConnection)):
            Pilot(sys.argv[2]).revoke(sys.stdin.read(), "pending")
    else:
        print(f"Python {sys.version.split()[0]}, SQLite {sqlite3.sqlite_version}")
        with TemporaryDirectory(prefix="nexus-sqlite-crash.", dir=sys.argv[1]) as scratch:
            rehearse(Path(scratch) / "pilot.db")
