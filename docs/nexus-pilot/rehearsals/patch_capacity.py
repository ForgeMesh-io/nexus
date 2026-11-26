"""Rehearsal: capacity, check-patch and decline through the installed CLI and loopback API. Tokens never printed.

Usage: python -I patch_capacity.py EMPTY_DIR VENV_BIN, where EMPTY_DIR/clone is
`git clone --depth 1 --branch forgemesh --no-checkout https://github.com/FRGMesh/anyps5.git`.
Fresh ledger, synthetic actors, nothing published.
"""
import json, os, subprocess, sys, time, urllib.request, urllib.error
from pathlib import Path

D = Path(sys.argv[1]); BIN = Path(sys.argv[2]); PORT = 8791
BASE = "8cfc7e611e0b0a2c22c6294a76c0fe7bbd8d506c"
db = D / "pilot.db"


def cli(action, **payload):
    r = subprocess.run([BIN / "nexus-pilot", db, action], input=json.dumps(payload), capture_output=True, text=True)
    return json.loads(r.stdout)


def api(who, op, **payload):
    body = json.dumps(payload).encode()
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}/v1/{op}", data=body, method="POST", headers={
        "Authorization": "Bearer " + tok[who], "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as res:
            return res.status, json.loads(res.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def show(label, value):
    print(f"{label:<48} {json.dumps(value)[:150]}")


def diff(change):
    w = D / "work"
    subprocess.run(["rm", "-rf", w]); (w / "docs/dev").mkdir(parents=True)
    for f in ("docs/dev/BUILD.md", "CONTRIBUTING.md"):
        (w / f).write_bytes(subprocess.run(["git", "-C", D / "clone", "show", f"{BASE}:{f}"], capture_output=True).stdout)
    g = lambda *a: subprocess.run(["git", "-C", w, *a], capture_output=True, text=True, check=True).stdout
    g("init", "-q"); g("add", "."); g("-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qm", "base")
    change(w)
    return g("diff", "--no-color")


show("initialize (active_limit=1)", cli("initialize", repository="frgmesh/anyps5", active_limit=1))
tok = {}
for actor, owner, role in [("alice", "alice", "contributor"), ("dana", "dana", "contributor"),
                           ("bob", "bob", "reviewer"), ("carol", "carol", "maintainer")]:
    tok[actor] = cli("enroll", actor=actor, owner=owner, role=role)
    assert len(tok[actor]) == 43
show("add-task build-doc (patch, docs/dev/BUILD.md)", cli("add-task", task="build-doc", issue=1, base=BASE,
     title="Clarify the relinker build", paths=["docs/dev/BUILD.md"], kind="patch"))
show("add-task dev-docs (patch, docs/dev/)", cli("add-task", task="dev-docs", issue=2, base=BASE,
     title="Dev docs", paths=["docs/dev/"], kind="patch"))
show("add-task notes (report)", cli("add-task", task="notes", issue=3, base=BASE, title="Notes"))

api_proc = subprocess.Popen([BIN / "nexus-participant-api", db, "--port", str(PORT)], stdout=subprocess.PIPE, text=True)
try:
    show("API listening", api_proc.stdout.readline().strip())
    st, lease = api("alice", "claim", task="build-doc"); show("alice claim build-doc", [st, lease])
    show("dana claim dev-docs (slot full)", api("dana", "claim", task="dev-docs"))
    patch = diff(lambda w: (w / "docs/dev/BUILD.md").write_text((w / "docs/dev/BUILD.md").read_text().replace(
        "Use a separate build directory for the full build.",
        "Use a separate build directory for the full build, for example `build-full`.", 1)))
    st, digest = api("alice", "submit", task="build-doc", lease=lease, report=patch)
    show(f"alice submit patch ({len(patch)} bytes)", [st, digest[:12] + "…"])
    show("dana claim (patch awaiting check holds slot)", api("dana", "claim", task="dev-docs"))
    show("bob discover (unchecked patch hidden)", api("bob", "discover"))
    show("bob review before check", api("bob", "review", task="build-doc", digest=digest, verdict="pass",
                                        evidence="early"))
    t0 = time.time()
    show("check-patch (bwrap, pinned clone)", cli("check-patch", task="build-doc", repository=str(D / "clone")))
    print(f"{'  check duration':<48} {time.time() - t0:.2f}s")
    st, found = api("bob", "discover")
    show("bob discover after check", [st, [(t["id"], t["kind"], t["checked"]) for t in found["tasks"]]])
    show("bob review pass", api("bob", "review", task="build-doc", digest=digest, verdict="pass",
                                evidence="Applied at base, wording only"))
    show("dana claim (awaiting maintainer holds slot)", api("dana", "claim", task="dev-docs"))
    show("carol decline", cli("decline", token=tok["carol"], task="build-doc", digest=digest))
    show("carol decline again (idempotent)", cli("decline", token=tok["carol"], task="build-doc", digest=digest))
    show("carol authorize after decline", cli("authorize", token=tok["carol"], task="build-doc", digest=digest))
    st, lease2 = api("dana", "claim", task="dev-docs"); show("dana claim dev-docs (slot freed)", [st, lease2])
    bad = diff(lambda w: (w / "CONTRIBUTING.md").write_text((w / "CONTRIBUTING.md").read_text() + "\nExtra.\n"))
    st, digest2 = api("dana", "submit", task="dev-docs", lease=lease2, report=bad)
    show("dana submit patch touching CONTRIBUTING.md", [st, digest2[:12] + "…"])
    show("check-patch", cli("check-patch", task="dev-docs", repository=str(D / "clone")))
    show("bob discover (rejected patch never shown)", api("bob", "discover"))
    show("alice claim notes (slot freed by failed check)", api("alice", "claim", task="notes"))
finally:
    api_proc.terminate(); api_proc.wait()
events = [(e["event"], e["task"], e["details"].get("result") or e["details"].get("verdict"))
          for e in json.loads(json.dumps(__import__("forgemesh.pilot", fromlist=["Pilot"]).Pilot(db).audit()))
          if e["event"] not in ("enrolled", "initialized", "task_added")]
print("audit:", events)
# The clone has no checkout: only .git exists, and the checks must leave it that way.
head = subprocess.run(["git", "-C", D / "clone", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
print("clone untouched:", head == BASE and [p.name for p in (D / "clone").iterdir()] == [".git"])
