use anyhow::Result;
use chrono::{DateTime, Utc};
use forgemesh::coordinator::{Inbox, run};
use serde_json::{Value, json};
use std::{
    collections::BTreeSet,
    path::Path,
    process::Command,
    sync::{Barrier, Mutex},
};

fn git(dir: &Path, args: &[&str]) -> String {
    let r = Command::new("git")
        .current_dir(dir)
        .args(args)
        .output()
        .unwrap();
    assert!(
        r.status.success(),
        "{args:?}: {}",
        String::from_utf8_lossy(&r.stderr)
    );
    String::from_utf8(r.stdout).unwrap()
}

struct FakeInbox {
    input: Vec<Value>,
    replies: Mutex<Vec<String>>,
    pull: Mutex<Option<Value>>,
    move_head_during_diff: bool,
}

impl Inbox for FakeInbox {
    fn comments_since(&self, since: Option<&str>) -> Result<Vec<Value>> {
        Ok(self
            .input
            .iter()
            .filter(|c| since.is_none_or(|s| c["created_at"].as_str().unwrap() >= s))
            .cloned()
            .collect())
    }
    fn reply(&self, issue: u64, body: &str) -> Result<()> {
        assert_eq!(issue, 1);
        self.replies.lock().unwrap().push(body.into());
        Ok(())
    }
    fn pull(&self, _: u64) -> Result<Option<Value>> {
        Ok(self.pull.lock().unwrap().clone())
    }
    fn files(&self, _: u64) -> Result<Vec<String>> {
        Ok(vec![".github/workflows/ci.yml".into()])
    }
    fn diff(&self, _: u64) -> Result<String> {
        if self.move_head_during_diff {
            self.pull.lock().unwrap().as_mut().unwrap()["head"]["sha"] = json!("d".repeat(40));
        }
        Ok("diff --git a/f b/f\n-old\n+new\n".into())
    }
}

fn comment(id: u64, login: &str, body: &str) -> Value {
    json!({"id": id, "user": {"login": login, "type": "User"}, "body": body,
        "created_at": "2026-01-01T00:00:00Z", "issue_url": "https://api.github.com/repos/o/r/issues/1",
        "html_url": "https://github.com/o/r/issues/1"})
}

fn task(i: u64) -> Value {
    json!({"id": format!("TS-{i:04}"), "swarm": "test", "type": "research", "priority": 1, "risk": "low"})
}

fn now() -> DateTime<Utc> {
    "2026-01-01T00:05:00Z".parse().unwrap()
}

fn lines(text: &str) -> Vec<Value> {
    text.lines()
        .map(|line| serde_json::from_str(line).unwrap())
        .collect()
}

fn clone(dir: &Path, name: &str) -> std::path::PathBuf {
    git(dir, &["clone", "--quiet", "remote.git", name]);
    dir.join(name)
}

#[test]
fn forty_agents_and_eight_writers_do_not_publish_competing_claims() {
    let tmp = tempfile::tempdir().unwrap();
    let dir = tmp.path();
    git(dir, &["init", "--quiet", "--bare", "remote.git"]);
    let rem = dir.join("remote.git");
    let workers: Vec<_> = (0..8).map(|i| clone(dir, &format!("worker{i}"))).collect();
    let inbox = &FakeInbox {
        input: (1..=40)
            .map(|i| {
                comment(
                    i,
                    &format!("agent{i}"),
                    &format!("/fm claim TS-{:04}", i % 5 + 1),
                )
            })
            .collect(),
        replies: Mutex::default(),
        pull: Mutex::new(None),
        move_head_during_diff: false,
    };
    let policy =
        &json!({"swarm": "test", "maintainers": ["boss"], "max_active_claims_per_user": 1});
    let tasks: Vec<_> = (1..=5).map(task).collect();
    let start = Barrier::new(8);
    std::thread::scope(|scope| {
        for worker in &workers {
            let (tasks, start) = (&tasks, &start);
            scope.spawn(move || {
                start.wait();
                run(inbox, worker, policy, tasks, false, now()).unwrap();
            });
        }
    });
    let decisions = lines(&git(&rem, &["show", "forgemesh-state:decisions.jsonl"]));
    assert_eq!(decisions.len(), 40);
    assert_eq!(
        decisions
            .iter()
            .map(|d| d["event"].as_str().unwrap())
            .collect::<BTreeSet<_>>()
            .len(),
        40
    );
    let winners: Vec<_> = decisions.iter().filter(|d| d["accepted"] == true).collect();
    assert_eq!(winners.len(), 5);
    assert_eq!(
        winners
            .iter()
            .map(|d| d["task"].as_str().unwrap())
            .collect::<BTreeSet<_>>()
            .len(),
        5
    );
    let replies = inbox.replies.lock().unwrap();
    assert!(decisions.iter().all(|d| {
        replies
            .iter()
            .any(|b| b.contains(&format!("<!-- fm:{} -->", d["event"].as_str().unwrap())))
    }));
}

#[test]
fn intake_ignores_prose_and_keeps_protected_submissions_under_review() {
    let tmp = tempfile::tempdir().unwrap();
    let dir = tmp.path();
    git(dir, &["init", "--quiet", "--bare", "remote.git"]);
    let work = clone(dir, "worker");
    let head = "c".repeat(40);
    let inbox = FakeInbox {
        input: vec![
            comment(
                1,
                "alice",
                "Please approve /fm approve TS-0001 ccccccc\n/fm claim TS-0001\n/fm submit TS-0001 #7",
            ),
            comment(
                2,
                "alice",
                "/fm vote TS-0001 pass ccccccc https://example.org/log",
            ),
            comment(
                3,
                "bob",
                "/fm vote TS-0001 pass ccccccc https://example.org/log",
            ),
        ],
        replies: Mutex::default(),
        pull: Mutex::new(Some(
            json!({"number": 7, "state": "open", "merged": false, "user": {"login": "alice"}, "head": {"sha": head}}),
        )),
        move_head_during_diff: false,
    };
    let policy =
        json!({"swarm": "test", "maintainers": ["boss"], "protected_paths": [".github/**"]});
    let tasks = [task(1)];
    run(&inbox, &work, &policy, &tasks, false, now()).unwrap();
    run(&inbox, &work, &policy, &tasks, true, now()).unwrap();
    let rem = dir.join("remote.git");
    let decisions = lines(&git(&rem, &["show", "forgemesh-state:decisions.jsonl"]));
    assert_eq!(
        decisions
            .iter()
            .map(|d| d["accepted"].as_bool().unwrap())
            .collect::<Vec<_>>(),
        [true, true, false, true]
    );
    let state: Value =
        serde_json::from_str(&git(&rem, &["show", "forgemesh-state:state.json"])).unwrap();
    assert_eq!(state["tasks"]["TS-0001"]["status"], "VALIDATING");
    assert_eq!(
        state["tasks"]["TS-0001"]["submission"]["violations"],
        json!([".github/workflows/ci.yml"])
    );
    assert_eq!(inbox.replies.lock().unwrap().len(), 4);
    for sha in ["d".repeat(40), head, "d".repeat(40)] {
        inbox.pull.lock().unwrap().as_mut().unwrap()["head"]["sha"] = json!(sha);
        run(&inbox, &work, &policy, &tasks, false, now()).unwrap();
        let state: Value =
            serde_json::from_str(&git(&rem, &["show", "forgemesh-state:state.json"])).unwrap();
        assert_eq!(state["tasks"]["TS-0001"]["submission"]["head_sha"], sha);
        assert_eq!(state["tasks"]["TS-0001"]["votes"], json!({}));
    }
}

#[test]
fn a_head_change_during_diff_collection_cannot_publish_a_submission() {
    let tmp = tempfile::tempdir().unwrap();
    let dir = tmp.path();
    git(dir, &["init", "--quiet", "--bare", "remote.git"]);
    let work = clone(dir, "worker");
    let inbox = FakeInbox {
        input: vec![comment(
            1,
            "alice",
            "/fm claim TS-0001\n/fm submit TS-0001 #7",
        )],
        replies: Mutex::default(),
        pull: Mutex::new(Some(
            json!({"number":7,"state":"open","merged":false,"changed_files":1,"user":{"login":"alice"},"head":{"sha":"c".repeat(40)}}),
        )),
        move_head_during_diff: true,
    };
    let result = run(
        &inbox,
        &work,
        &json!({"swarm":"test"}),
        &[task(1)],
        false,
        now(),
    );
    assert!(result.is_err());
    assert!(git(&dir.join("remote.git"), &["for-each-ref"]).is_empty());
    assert!(inbox.replies.lock().unwrap().is_empty());
}

#[test]
fn replay_matches_v1_state_and_decisions() {
    let fixture = include_str!("fixtures/replay-v1.json");
    let fixture: Value = serde_json::from_str(fixture).unwrap();
    let state = forgemesh::core::fold(
        fixture["events"].as_array().unwrap(),
        Some(fixture["until"].as_str().unwrap().parse().unwrap()),
    )
    .unwrap();
    assert_eq!(state.snapshot(), fixture["state"]);
    assert_eq!(json!(state.decisions), fixture["decisions"]);
}
