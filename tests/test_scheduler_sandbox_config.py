import json
from pathlib import Path

import pytest

from forgemesh import commands, config, sandbox, scheduler
from forgemesh.core import fold
from forgemesh.fingerprint import patch_id

from .test_core import SHA, base, ev, submit, task

DIGEST = "ghcr.io/forgemesh-io/nexus@sha256:" + "0" * 64


# ---- scheduler --------------------------------------------------------------

def _saturated(n_submitted=12):
    ts = [task(f"NX-{i:04d}") for i in range(1, n_submitted + 3)] + [task("NX-0900", type="reviewer")]
    events = base(*ts, max_active_claims_per_user=1)
    for i in range(1, n_submitted + 1):
        tid = f"NX-{i:04d}"
        events += [ev("claim", task=tid, actor=f"dev{i}"), submit(actor=f"dev{i}", t=tid, pr=i, sha=f"{i:040x}")]
    return fold(events)


def test_validation_pressure_redirects_most_participants():
    s = _saturated()
    modes = [scheduler.mode_for(s, f"user{i}", "2026-01-01") for i in range(200)]
    assert modes.count("validate") > 170  # ~95% when the queue is saturated


def test_low_queue_favours_development():
    s = fold(base(task()))
    assert scheduler.mode_for(s, "anyone", "x") == "develop"


def test_recommend_skips_own_work_and_hardware_mismatch():
    ts = [task(), task("NX-0002", hardware=["gpu:amd"]), task("NX-0003")]
    s = fold(base(*ts) + [ev("claim", task="NX-0003", actor="bob"), submit(actor="bob", t="NX-0003", pr=3)])
    rec = scheduler.recommend(s, "bob", {"os:linux"})
    assert "NX-0003" not in rec["validate"] and "NX-0002" not in rec["claim"] and "NX-0001" in rec["claim"]
    rec = scheduler.recommend(s, "carol", {"os:linux", "gpu:amd"})
    assert rec["validate"] == ["NX-0003"] and rec["claim"][0] == "NX-0002"  # rare hardware first


def test_recommend_prefers_blockers_and_priority():
    ts = [task("NX-0001", priority=2), task("NX-0002", priority=2), task("NX-0003", depends_on=["NX-0002"])]
    rec = scheduler.recommend(fold(base(*ts)), "a", set())
    assert rec["claim"][0] == "NX-0002"


# ---- commands (untrusted input) ---------------------------------------------

def test_parser_is_strict():
    body = "please do /fm claim NX-0001\n/fm claim NX-0001\n/fm claim NX-0001; rm -rf /\n/fm vote NX-0001 pass abcdef1 https://x/y"
    out = commands.parse(body)
    assert [c["kind"] for c in out] == ["claim", "invalid", "vote"]


def test_parser_limits_commands_per_comment():
    assert len(commands.parse("\n".join(["/fm claim NX-0001"] * 50))) == commands.MAX_COMMANDS_PER_COMMENT


# ---- fingerprint ------------------------------------------------------------

def test_patch_id_ignores_whitespace_and_positions():
    a = "diff --git a/f b/f\n@@ -1,2 +1,2 @@\n ctx\n-x = 1\n+x = 2\n"
    b = "diff --git a/f b/f\n@@ -40,2 +40,2 @@\n other\n-x  =  1\n+x = 2\n"
    assert patch_id(a) == patch_id(b) != patch_id(a.replace("2", "3"))


# ---- sandbox ----------------------------------------------------------------

def test_sandbox_defaults_are_locked_down(tmp_path):
    args = sandbox.docker_args(DIGEST, tmp_path, ["pytest"])
    joined = " ".join(args)
    for flag in ("--network none", "--cap-drop ALL", "no-new-privileges", "--read-only", "--user 1000:1000", "--pids-limit"):
        assert flag in joined
    assert "docker.sock" not in joined and str(Path.home()) + "," not in joined
    assert "/dev/dri" not in joined


def test_sandbox_requires_digest_pinned_image(tmp_path):
    with pytest.raises(ValueError, match="digest"):
        sandbox.docker_args("ghcr.io/forgemesh-io/nexus:latest", tmp_path, ["true"])


def test_sandbox_refuses_home_and_parents(tmp_path):
    for bad in (Path.home(), Path("/")):
        with pytest.raises(ValueError, match="refusing"):
            sandbox.docker_args(DIGEST, bad, ["true"])


# ---- config -----------------------------------------------------------------

def _write_cfg(root: Path, tasks, policy=None):
    d = root / ".forgemesh" / "tasks"
    d.mkdir(parents=True)
    (root / ".forgemesh" / "policy.json").write_text(json.dumps(policy or {"swarm": "nexus", "maintainers": ["boss"]}))
    for t in tasks:
        (d / f"{t['id']}.json").write_text(json.dumps(t))


def test_config_valid(tmp_path):
    _write_cfg(tmp_path, [task(), task("NX-0002", depends_on=["NX-0001"])])
    policy, tasks = config.load(tmp_path)
    assert len(tasks) == 2


@pytest.mark.parametrize("bad", [
    {"risk": "extreme"},
    {"depends_on": ["NX-9999"]},
    {"swarm": "vie"},
    {"unexpected": True},
    {"acceptance": []},
])
def test_config_rejects_invalid_tasks(tmp_path, bad):
    _write_cfg(tmp_path, [{**task(), **bad}])
    with pytest.raises(Exception):
        config.load(tmp_path)


def test_config_rejects_cycles(tmp_path):
    _write_cfg(tmp_path, [task(depends_on=["NX-0002"]), task("NX-0002", depends_on=["NX-0001"])])
    with pytest.raises(ValueError, match="cycle"):
        config.load(tmp_path)


def test_config_events_only_on_change():
    p, t = {"swarm": "nexus", "maintainers": ["b"]}, [task()]
    first = config.config_events(p, t, [], "2026-01-01T00:00:00Z")
    assert len(first) == 2
    assert config.config_events(p, t, first, "2026-01-01T00:00:00Z") == []
