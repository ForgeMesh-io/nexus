"""Single-repository ledger for the bounded, text-only Nexus pilot."""

from contextlib import closing, contextmanager
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import time


MAX_TASKS = 32
MAX_ACTORS = 32
MAX_ATTEMPTS = 8
ROLES = {"contributor", "reviewer", "maintainer", "publisher"}
SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    repository TEXT NOT NULL, active_limit INTEGER NOT NULL,
    lease_seconds INTEGER NOT NULL, publication_limit INTEGER NOT NULL,
    stopped INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS actors (
    id TEXT PRIMARY KEY, owner TEXT NOT NULL, role TEXT NOT NULL,
    credential TEXT UNIQUE NOT NULL, revoked INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY, issue INTEGER UNIQUE NOT NULL, base TEXT NOT NULL, title TEXT NOT NULL,
    actor TEXT REFERENCES actors(id), expires INTEGER, attempt INTEGER NOT NULL DEFAULT 0,
    digest TEXT, report TEXT, reviewer TEXT REFERENCES actors(id), verdict TEXT, evidence TEXT
);
CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY, at INTEGER NOT NULL, event TEXT NOT NULL,
    actor TEXT, task TEXT, details TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS publications (
    task TEXT PRIMARY KEY REFERENCES tasks(id), marker TEXT UNIQUE NOT NULL,
    approver TEXT NOT NULL REFERENCES actors(id), started INTEGER NOT NULL DEFAULT 0,
    receipt INTEGER UNIQUE
);
"""


class PilotError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _match(value, pattern):
    if not isinstance(value, str) or not re.fullmatch(pattern, value):
        raise PilotError("invalid_input")


def _id(value):
    _match(value, r"[a-z0-9][a-z0-9_-]{0,63}")


def _text(value, limit):
    if not isinstance(value, str) or not value.strip() or "\0" in value:
        raise PilotError("invalid_input")
    try:
        data = value.encode("utf-8")
    except UnicodeError:
        raise PilotError("invalid_input") from None
    if len(data) > limit:
        raise PilotError("invalid_input")
    return data


class Pilot:
    def __init__(self, path, *, clock=time.time):
        self.path = Path(path).absolute()
        self.clock = clock

    @contextmanager
    def _db(self, *, write=False):
        if not self.path.is_file():
            raise PilotError("not_initialized")
        mode = "rw" if write else "ro"
        with closing(sqlite3.connect(f"{self.path.as_uri()}?mode={mode}", uri=True)) as db, db:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys = ON")
            db.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield db

    def initialize(self, repository: str, *, active_limit: int = 2, lease_seconds: int = 900,
                   publication_limit: int = 1):
        """Operator-only; use an operator-owned directory with mode 0700."""
        _match(repository, r"[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_][A-Za-z0-9_.-]{0,99}")
        if (type(active_limit) is not int or not 0 <= active_limit <= MAX_TASKS
                or type(lease_seconds) is not int or not 1 <= lease_seconds <= 86_400
                or type(publication_limit) is not int or not 0 <= publication_limit <= MAX_TASKS):
            raise PilotError("invalid_input")
        try:
            fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            raise PilotError("already_initialized") from None
        os.close(fd)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.executescript("BEGIN IMMEDIATE;" + SCHEMA)
            db.execute("INSERT INTO settings VALUES (1, ?, ?, ?, ?, 0)",
                       (repository.lower(), active_limit, lease_seconds, publication_limit))
            self._event(db, "initialized", repository=repository.lower(),
                        active_limit=active_limit, lease_seconds=lease_seconds,
                        publication_limit=publication_limit)

    def _event(self, db, event, actor=None, task=None, **details):
        db.execute("INSERT INTO audit(at,event,actor,task,details) VALUES(?,?,?,?,?)",
                   (int(self.clock()), event, actor, task, json.dumps(details, sort_keys=True)))

    @staticmethod
    def _settings(db, *, allow_stopped=False):
        settings = db.execute("SELECT * FROM settings").fetchone()
        if settings is None:
            raise PilotError("not_initialized")
        if settings["stopped"] and not allow_stopped:
            raise PilotError("stopped")
        return settings

    @staticmethod
    def _actor(db, token, role=None):
        if not isinstance(token, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{43}", token):
            raise PilotError("unauthorized")
        actor = db.execute("SELECT * FROM actors WHERE credential=? AND revoked=0",
                           (sha256(token.encode()).hexdigest(),)).fetchone()
        if actor is None or (role is not None and actor["role"] != role):
            raise PilotError("unauthorized")
        return actor

    def enroll(self, actor: str, owner: str, role: str) -> str:
        """Operator-only; map aliases to the same enrolled human owner."""
        _id(actor)
        _id(owner)
        if not isinstance(role, str) or role not in ROLES:
            raise PilotError("invalid_input")
        with self._db(write=True) as db:
            self._settings(db)
            if db.execute("SELECT count(*) FROM actors").fetchone()[0] >= MAX_ACTORS:
                raise PilotError("capacity")
            token = secrets.token_urlsafe(32)
            created = db.execute("INSERT OR IGNORE INTO actors(id,owner,role,credential) VALUES(?,?,?,?)",
                                 (actor, owner, role, sha256(token.encode()).hexdigest()))
            if not created.rowcount:
                raise PilotError("conflict")
            self._event(db, "enrolled", actor=actor, owner=owner, role=role)
        return token

    def add_task(self, task: str, issue: int, base: str, title: str):
        """Operator-only; the selected issue and exact revision are the approved scope."""
        _id(task)
        _match(base, r"[0-9a-f]{40}")
        _text(title, 256)
        if type(issue) is not int or not 1 <= issue <= 2**31 - 1:
            raise PilotError("invalid_input")
        with self._db(write=True) as db:
            self._settings(db)
            if db.execute("SELECT count(*) FROM tasks").fetchone()[0] >= MAX_TASKS:
                raise PilotError("capacity")
            created = db.execute("INSERT OR IGNORE INTO tasks(id,issue,base,title) VALUES(?,?,?,?)",
                                 (task, issue, base, title))
            if not created.rowcount:
                raise PilotError("conflict")
            self._event(db, "task_added", task=task, issue=issue, base=base)

    def discover(self, token: str) -> dict:
        with self._db() as db:
            actor = self._actor(db, token)
            settings = self._settings(db)
            tasks = []
            if actor["role"] == "contributor" and settings["active_limit"]:
                tasks = db.execute("""SELECT id,issue,base,title FROM tasks
                    WHERE digest IS NULL AND attempt < ? AND (expires IS NULL OR expires <= ?)
                    ORDER BY id""", (MAX_ATTEMPTS, int(self.clock())))
            elif actor["role"] == "reviewer":
                tasks = db.execute("""SELECT t.id,issue,base,title,digest,report FROM tasks AS t
                    JOIN actors AS a ON t.actor=a.id
                    WHERE digest IS NOT NULL AND verdict IS NULL AND a.owner != ? AND a.revoked=0
                    ORDER BY t.id""", (actor["owner"],))
            return {"repository": settings["repository"], "tasks": [dict(task) for task in tasks]}

    @staticmethod
    def _task(db, task):
        _id(task)
        row = db.execute("SELECT * FROM tasks WHERE id=?", (task,)).fetchone()
        if row is None:
            raise PilotError("unknown_task")
        return row

    def claim(self, token: str, task: str) -> int:
        with self._db(write=True) as db:
            actor = self._actor(db, token, "contributor")
            settings = self._settings(db)
            row = self._task(db, task)
            now = int(self.clock())
            if row["digest"] is not None:
                raise PilotError("conflict")
            if row["expires"] is not None and row["expires"] > now:
                if row["actor"] == actor["id"]:
                    return row["attempt"]
                raise PilotError("busy")
            if row["attempt"] >= MAX_ATTEMPTS:
                raise PilotError("attempt_limit")
            active, owned = db.execute("""SELECT count(*), sum(a.owner = ?) FROM tasks AS t
                JOIN actors AS a ON t.actor=a.id WHERE t.digest IS NULL AND t.expires > ?""",
                (actor["owner"], now)).fetchone()
            # Reports still waiting for a human decision hold their slot, so intake stops when reviewers fall behind.
            waiting = db.execute("""SELECT count(*) FROM tasks AS t JOIN actors AS a ON t.actor=a.id
                WHERE t.digest IS NOT NULL AND a.revoked=0 AND (t.verdict IS NULL OR t.verdict='pass')
                AND t.id NOT IN (SELECT task FROM publications)""").fetchone()[0]
            if owned or active + waiting >= settings["active_limit"]:
                raise PilotError("capacity")
            attempt = row["attempt"] + 1
            expires = now + settings["lease_seconds"]
            db.execute("UPDATE tasks SET actor=?,expires=?,attempt=? WHERE id=?",
                       (actor["id"], expires, attempt, task))
            self._event(db, "claimed", actor["id"], task, attempt=attempt, expires=expires)
            return attempt

    def submit(self, token: str, task: str, lease: int, report: str) -> str:
        digest = sha256(_text(report, 8_192)).hexdigest()
        if type(lease) is not int or not 1 <= lease <= MAX_ATTEMPTS:
            raise PilotError("invalid_input")
        with self._db(write=True) as db:
            actor = self._actor(db, token, "contributor")
            self._settings(db)
            row = self._task(db, task)
            if row["actor"] != actor["id"] or row["attempt"] != lease:
                raise PilotError("stale_lease")
            if row["digest"] is not None:
                if row["digest"] == digest:
                    return digest
                raise PilotError("conflict")
            if row["expires"] is None or row["expires"] <= int(self.clock()):
                raise PilotError("stale_lease")
            db.execute("UPDATE tasks SET digest=?, report=?, expires=NULL WHERE id=?", (digest, report, task))
            self._event(db, "submitted", actor["id"], task, digest=digest, attempt=lease)
            return digest

    def review(self, token: str, task: str, digest: str, verdict: str, evidence: str) -> str:
        _match(digest, r"[0-9a-f]{64}")
        if verdict not in ("pass", "reject"):
            raise PilotError("invalid_input")
        proof = sha256(_text(evidence, 2_048)).hexdigest()
        with self._db(write=True) as db:
            reviewer = self._actor(db, token, "reviewer")
            self._settings(db)
            row = self._task(db, task)
            if row["digest"] != digest:
                raise PilotError("stale_digest")
            author = db.execute("SELECT owner, revoked FROM actors WHERE id=?", (row["actor"],)).fetchone()
            if author["owner"] == reviewer["owner"]:
                raise PilotError("independence")
            if author["revoked"]:
                raise PilotError("withdrawn")
            if row["verdict"] == "declined":
                raise PilotError("declined")
            if row["reviewer"] is None:
                db.execute("UPDATE tasks SET reviewer=?,verdict=?,evidence=? WHERE id=?",
                           (reviewer["id"], verdict, evidence, task))
                self._event(db, "reviewed", reviewer["id"], task, digest=digest, verdict=verdict, proof=proof)
            elif (row["reviewer"], row["verdict"], row["evidence"]) != (reviewer["id"], verdict, evidence):
                raise PilotError("conflict")
            return "validated" if verdict == "pass" else "rejected"

    @staticmethod
    def _check_active(db, *actors):
        for actor in actors:
            if not db.execute("SELECT 1 FROM actors WHERE id=? AND revoked=0", (actor,)).fetchone():
                raise PilotError("withdrawn")

    def inspect_report(self, token: str, task: str) -> dict:
        with self._db() as db:
            self._actor(db, token, "maintainer")
            settings = self._settings(db, allow_stopped=True)
            row = self._task(db, task)
            if row["digest"] is None:
                raise PilotError("no_report")
            return {"repository": settings["repository"], **{key: row[key] for key in (
                "issue", "base", "title", "report", "digest", "actor", "reviewer", "verdict", "evidence",
            )}}

    def authorize(self, token: str, task: str, digest: str) -> str:
        _match(digest, r"[0-9a-f]{64}")
        with self._db(write=True) as db:
            approver = self._actor(db, token, "maintainer")
            settings = self._settings(db)
            row = self._task(db, task)
            if row["digest"] != digest:
                raise PilotError("stale_digest")
            if row["verdict"] != "pass":
                raise PilotError("not_validated")
            self._check_active(db, row["actor"], row["reviewer"])
            existing = db.execute("SELECT * FROM publications WHERE task=?", (task,)).fetchone()
            if existing:
                self._check_active(db, existing["approver"])
                return existing["marker"]
            if db.execute("SELECT count(*) FROM publications").fetchone()[0] >= settings["publication_limit"]:
                raise PilotError("publication_quota")
            marker = secrets.token_hex(16)
            db.execute("INSERT INTO publications(task,marker,approver) VALUES(?,?,?)",
                       (task, marker, approver["id"]))
            self._event(db, "authorized", approver["id"], task, digest=digest, marker=marker)
            return marker

    def decline(self, token: str, task: str, digest: str):
        """Maintainer refusal of an exact report; the reviewer's verdict stays in the audit."""
        _match(digest, r"[0-9a-f]{64}")
        with self._db(write=True) as db:
            maintainer = self._actor(db, token, "maintainer")
            self._settings(db, allow_stopped=True)
            row = self._task(db, task)
            if row["digest"] != digest:
                raise PilotError("stale_digest")
            if db.execute("SELECT 1 FROM publications WHERE task=?", (task,)).fetchone():
                raise PilotError("conflict")
            if row["verdict"] != "declined":
                db.execute("UPDATE tasks SET verdict='declined' WHERE id=?", (task,))
                self._event(db, "declined", maintainer["id"], task, digest=digest)

    def begin_dispatch(self, token: str, task: str, current_base: str) -> dict | None:
        """Grant a single send attempt; an absent receipt after this point is ambiguous."""
        _match(current_base, r"[0-9a-f]{40}")
        with self._db(write=True) as db:
            publisher = self._actor(db, token, "publisher")
            settings = self._settings(db)
            row = self._task(db, task)
            intent = db.execute("SELECT * FROM publications WHERE task=?", (task,)).fetchone()
            if not intent or intent["started"]:
                return None
            self._check_active(db, row["actor"], row["reviewer"], intent["approver"])
            if row["base"] != current_base:
                raise PilotError("stale_base")
            db.execute("UPDATE publications SET started=1 WHERE task=?", (task,))
            self._event(db, "dispatch_started", publisher["id"], task, marker=intent["marker"])
            return self._publication(settings, row, intent)

    @staticmethod
    def _publication(settings, task, intent):
        return {"repository": settings["repository"], "marker": intent["marker"],
                **{key: task[key] for key in ("issue", "base", "digest", "report")}}

    def dispatched(self, token: str, task: str) -> dict | None:
        """Inspect an already-started dispatch without granting another send."""
        with self._db() as db:
            self._actor(db, token, "publisher")
            settings = self._settings(db, allow_stopped=True)
            row = self._task(db, task)
            intent = db.execute("SELECT * FROM publications WHERE task=? AND started=1", (task,)).fetchone()
            if intent:
                return self._publication(settings, row, intent)

    def pending_target(self, token: str, task: str) -> tuple[str, int] | None:
        with self._db() as db:
            self._actor(db, token, "publisher")
            settings = self._settings(db)
            row = self._task(db, task)
            intent = db.execute("SELECT * FROM publications WHERE task=? AND started=0", (task,)).fetchone()
            if intent:
                self._check_active(db, row["actor"], row["reviewer"], intent["approver"])
                return settings["repository"], row["issue"]

    def record_publication(self, token: str, marker: str, receipt: int) -> int:
        """Record only an independently observed receipt, including after a stop."""
        _match(marker, r"[0-9a-f]{32}")
        if type(receipt) is not int or not 1 <= receipt <= 2**63 - 1:
            raise PilotError("invalid_input")
        with self._db(write=True) as db:
            publisher = self._actor(db, token, "publisher")
            intent = db.execute("SELECT * FROM publications WHERE marker=? AND started=1", (marker,)).fetchone()
            if not intent:
                raise PilotError("unknown_dispatch")
            if intent["receipt"] == receipt:
                return receipt
            if intent["receipt"] is not None or db.execute(
                    "SELECT 1 FROM publications WHERE receipt=?", (receipt,)).fetchone():
                raise PilotError("conflict")
            db.execute("UPDATE publications SET receipt=? WHERE marker=?", (receipt, marker))
            self._event(db, "published", publisher["id"], intent["task"], marker=marker, receipt=receipt)
            return receipt

    def revoke(self, token: str, actor: str):
        _id(actor)
        with self._db(write=True) as db:
            maintainer = self._actor(db, token, "maintainer")
            target = db.execute("SELECT revoked FROM actors WHERE id=?", (actor,)).fetchone()
            if target is None:
                raise PilotError("unknown_actor")
            if not target["revoked"]:
                db.execute("UPDATE actors SET revoked=1 WHERE id=?", (actor,))
                db.execute("UPDATE tasks SET expires=NULL WHERE actor=? AND digest IS NULL", (actor,))
                self._event(db, "revoked", maintainer["id"], revoked=actor)

    def stop(self, token: str):
        with self._db(write=True) as db:
            maintainer = self._actor(db, token, "maintainer")
            if not self._settings(db, allow_stopped=True)["stopped"]:
                db.execute("UPDATE settings SET stopped=1")
                self._event(db, "stopped", maintainer["id"])

    def audit(self) -> list[dict]:
        """Operator-only, including after an emergency stop."""
        with self._db() as db:
            return [dict(row) | {"details": json.loads(row["details"])}
                    for row in db.execute("SELECT * FROM audit ORDER BY id")]
