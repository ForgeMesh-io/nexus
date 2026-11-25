import json
from pathlib import Path

import pytest

from forgemesh import commands, config, sandbox, scheduler
from forgemesh.__main__ import main
from forgemesh.core import SYSTEM, fold
from forgemesh.journal import dumps
from forgemesh.fingerprint import patch_id

from .test_core import SHA, base, ev, submit, task, vote

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


def test_recommend_falls_back_to_claims_when_the_validation_queue_is_ineligible():
    events = base(task(), task("NX-0002"), validation_pressure={"dev_share_low": 0})
    state = fold(events + [ev("claim", task="NX-0001"), submit()])
    rec = scheduler.recommend(state, "alice", set())
    assert rec["mode"] == "develop"
    assert rec["claim"] == ["NX-0002"] and rec["validate"] == []


def test_maintainer_only_blocker_does_not_request_more_passes():
    events = base(task(), task("NX-0002")) + [
        ev("claim", task="NX-0001"), submit(violations=["protected.py"]), vote("bob"),
    ]
    rec = scheduler.recommend(fold(events), "carol", set())
    assert rec["in_review"] == 1 and rec["validation_queue"] == 0
    assert rec["mode"] == "develop" and rec["claim"] == ["NX-0002"]
    assert rec["validate"] == [] and rec["validation_targets"] == {}


def test_recommend_reserves_a_missing_trusted_pass_for_trusted_actors():
    events = base(task(risk="high")) + [ev("claim", task="NX-0001"), submit(pr=7), vote("bob")]
    assert scheduler.recommend(fold(events), "carol", set())["validate"] == ["NX-0001"]
    state = fold(events + [vote("carol")])
    assert scheduler.recommend(state, "dave", set())["validate"] == []
    rec = scheduler.recommend(state, "trusty", set())
    assert rec["validation_queue"] == 1 and rec["validate"] == ["NX-0001"]
    assert rec["validation_targets"]["NX-0001"] == {
        "pr": 7, "head_sha": SHA,
        "missing": {"independent_passes": 0, "trusted_pass": True, "maintainer_approval": True},
    }


@pytest.mark.parametrize("paused", [False, True])
def test_recommend_does_not_offer_claims_the_policy_would_reject(paused):
    events = base(task(), task("NX-0002"), task("NX-0003"), max_active_claims_per_user=1)
    events += [ev("claim", task="NX-0001"), ev("claim", task="NX-0003", actor="bob"),
               submit(actor="bob", t="NX-0003", pr=3),
               ev("policy", actor=SYSTEM, policy={**events[0]["policy"], "paused": paused})]
    state = fold(events)
    rec = scheduler.recommend(state, "alice", set())
    assert rec["claim"] == [] and rec["validate"] == ["NX-0003"] and rec["mode"] == "validate"
    assert scheduler.recommend(state, "carol", set())["claim"] == ([] if paused else ["NX-0002"])


def test_next_without_execution_filters_claims_and_validation_without_probing(tmp_path, capsys, monkeypatch):
    tasks = [task(f"NX-000{i}", **settings) for i, settings in enumerate((
        {"execution": "none"}, {}, {"execution": "none"}, {"execution": "container"},
        {"execution": "none", "hardware": ["os:linux"]},
        {"execution": "none", "validation": {"commands": ["pytest"]}},
    ), 1)]
    events = base(*tasks) + [
        ev("claim", task="NX-0003"), submit(t="NX-0003", pr=3),
        ev("claim", task="NX-0004", actor="bob"), submit(actor="bob", t="NX-0004", pr=4),
    ]
    journal = tmp_path / "journal.jsonl"
    journal.write_text("".join(dumps(e) + "\n" for e in events))

    def unexpected_probe():
        pytest.fail("read-only task selection probed the machine")

    monkeypatch.setattr("forgemesh.capabilities.detect", unexpected_probe)
    assert main(["next", "--journal", str(journal), "--actor", "carol", "--no-execution"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["claim"] == ["NX-0001"]
    assert result["validate"] == ["NX-0003"]
    assert result["validation_targets"]["NX-0003"]["head_sha"] == SHA


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
