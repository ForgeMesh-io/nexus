"""Measure the installed pilot offline on a fresh ledger on the selected filesystem."""

from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from functools import partial
from hashlib import sha256
from importlib.metadata import version
from math import ceil
from pathlib import Path
import sqlite3
from statistics import median
import sys
from tempfile import TemporaryDirectory
from threading import Barrier, local
from time import perf_counter_ns
from unittest.mock import patch

from forgemesh.pilot import Pilot, PilotError


TASKS = 30
REPEATS = 5
REPORT = "Synthetic report.\n".ljust(8192, ".")
DIGEST = sha256(REPORT.encode()).hexdigest()
clock = local()
connect = sqlite3.connect


class TimedConnection(sqlite3.Connection):
    def execute(self, sql, parameters=()):
        if sql != "BEGIN IMMEDIATE":
            return super().execute(sql, parameters)
        start = perf_counter_ns()
        try:
            return super().execute(sql, parameters)
        finally:
            clock.begin = perf_counter_ns() - start


def expect_refusal(code, operation, *args):
    try:
        operation(*args)
    except PilotError as error:
        assert error.code == code, error.code
    else:
        raise AssertionError(f"Expected {code}")


def snapshot(source, destination):
    with closing(connect(f"{source.as_uri()}?mode=ro", uri=True)) as origin:
        with closing(connect(destination)) as target:
            origin.backup(target)


def check_integrity(path):
    with closing(connect(f"{path.as_uri()}?mode=ro", uri=True)) as db:
        assert db.execute("PRAGMA integrity_check").fetchall() == [("ok",)]


def run(directory, clients):
    ledger = Pilot(directory / "pilot.db")
    ledger.initialize("example/project", active_limit=TASKS, publication_limit=0)
    maintainer = ledger.enroll("maintainer", "maintainer", "maintainer")
    reviewer = ledger.enroll("reviewer", "reviewer", "reviewer")
    tasks = [(f"report-{number}", ledger.enroll(f"author-{number}", f"author-{number}", "contributor"))
             for number in range(1, TASKS + 1)]
    for issue, (task, _) in enumerate(tasks, 1):
        ledger.add_task(task, issue, "b" * 40, f"Synthetic issue {issue}")

    barrier = Barrier(clients, timeout=20)

    def worker(batch):
        samples = []

        def write(operation, *args):
            barrier.wait()
            clock.begin = None
            start = perf_counter_ns()
            result = operation(*args)
            elapsed = perf_counter_ns() - start
            assert clock.begin is not None and 0 <= clock.begin <= elapsed
            samples.append((clock.begin, elapsed))
            return result

        try:
            for task, token in batch:
                assert ledger.discover(token)["repository"] == "example/project"
                lease = write(ledger.claim, token, task)
                assert lease == 1
                assert write(ledger.submit, token, task, lease, REPORT) == DIGEST
                assert write(ledger.review, reviewer, task, DIGEST, "pass", "Synthetic review") == "validated"
                write(expect_refusal, "publication_quota", ledger.authorize, maintainer, task, DIGEST)
                write(ledger.decline, maintainer, task, DIGEST)
        except Exception:
            barrier.abort()
            raise
        return samples

    with patch("forgemesh.pilot.sqlite3.connect", partial(connect, factory=TimedConnection)):
        with ThreadPoolExecutor(max_workers=clients) as executor:
            samples = [sample for batch in executor.map(worker, (tasks[i::clients] for i in range(clients)))
                       for sample in batch]
    assert len(samples) == TASKS * 5

    ledger.revoke(maintainer, "author-1")
    ledger.stop(maintainer)
    audit = ledger.audit()
    assert Counter(event["event"] for event in audit) == {
        "initialized": 1, "enrolled": TASKS + 2, "task_added": TASKS, "claimed": TASKS,
        "submitted": TASKS, "reviewed": TASKS, "declined": TASKS, "revoked": 1, "stopped": 1,
    }

    backup = directory / "backup.db"
    start = perf_counter_ns()
    snapshot(ledger.path, backup)
    check_integrity(backup)
    assert Pilot(backup).audit() == audit
    backup_ns = perf_counter_ns() - start

    start = perf_counter_ns()
    restore_dir = directory / "restored"
    restore_dir.mkdir(mode=0o700)
    restored = Pilot(restore_dir / "pilot.db")
    snapshot(backup, restored.path)
    check_integrity(restored.path)
    assert restored.audit() == audit
    expect_refusal("unauthorized", restored.discover, tasks[0][1])
    expect_refusal("stopped", restored.discover, tasks[1][1])
    assert restored.inspect_report(maintainer, tasks[-1][0])["report"] == REPORT
    with closing(connect(f"{restored.path.as_uri()}?mode=ro", uri=True)) as db:
        assert db.execute("SELECT publication_limit FROM settings").fetchone() == (0,)
        assert db.execute("SELECT count(*) FROM publications").fetchone() == (0,)
        assert db.execute("PRAGMA journal_mode").fetchone() == ("delete",)
    restore_ns = perf_counter_ns() - start
    return samples, backup_ns, restore_ns, ledger.path.stat().st_size


def percentiles(samples):
    ordered = sorted(samples)
    return "/".join(f"{ordered[ceil(p * len(ordered)) - 1] / 1e6:.3f}" for p in (.50, .95, .99, 1))


def median_max(samples):
    return f"{median(samples) / 1e6:.3f}/{max(samples) / 1e6:.3f}"


if __name__ == "__main__":
    print(f"Nexus {version('forgemesh-nexus')}, Python {sys.version.split()[0]}, SQLite {sqlite3.sqlite_version}")
    print(f"{REPEATS} fresh ledgers per profile; {TASKS} reports per ledger; journal=delete; publication_limit=0")
    print("clients | writes | BEGIN p50/p95/p99/max ms | calls p50/p95/p99/max ms"
          " | backup median/max ms | restore median/max ms | ledger bytes")
    with TemporaryDirectory(prefix="nexus-sqlite-load.", dir=sys.argv[1]) as scratch:
        for clients in (1, 2, 6, 30):
            runs = []
            for repeat in range(REPEATS):
                directory = Path(scratch) / f"{clients}-{repeat}"
                directory.mkdir(mode=0o700)
                runs.append(run(directory, clients))
            begin, calls = zip(*(sample for samples, _, _, _ in runs for sample in samples))
            _, backups, restores, sizes = zip(*runs)
            print(f"{clients} | {len(begin)} | {percentiles(begin)} | {percentiles(calls)}"
                  f" | {median_max(backups)} | {median_max(restores)} | {min(sizes)}–{max(sizes)}")
    print("PASS: 20/20 ledgers and restores; 600 quota refusals; exact audit, integrity, stop, revocation; 0 publications")
