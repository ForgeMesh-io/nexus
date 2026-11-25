use serde_json::{Value, json};
use std::{fs, path::Path, process::Command};

fn run(args: &[&str]) -> std::process::Output {
    Command::new(env!("CARGO_BIN_EXE_forgemesh"))
        .args(args)
        .output()
        .unwrap()
}

fn output(args: &[&str]) -> Value {
    let result = run(args);
    assert!(
        result.status.success(),
        "{}",
        String::from_utf8_lossy(&result.stderr)
    );
    serde_json::from_slice(&result.stdout).expect("command must emit JSON")
}

const SHA: &str = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
const SHA2: &str = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb";
const TIME: &str = "2026-01-01T00:00:00Z";

fn task(id: &str, requirements: &[&str]) -> Value {
    json!({"id": id, "swarm": "test", "title": "Example task", "objective": "Test a real behavior",
        "type": "research", "priority": 1, "risk": "low", "acceptance": ["Provide evidence"],
        "hardware": requirements})
}

fn journal(dir: &Path, tasks: &[Value], requests: &[Value]) -> String {
    let policy = json!({"swarm": "test", "maintainers": ["boss"], "validation_pressure": {"dev_share_low": 0}});
    let mut events = vec![json!({"kind": "policy", "actor": "@system", "policy": policy})];
    events.extend(
        tasks
            .iter()
            .map(|task| json!({"kind": "task", "actor": "@system", "task": task})),
    );
    events.extend_from_slice(requests);
    let mut text = String::new();
    for (i, event) in events.iter_mut().enumerate() {
        event["id"] = json!(format!("e{i}"));
        if event["time"].is_null() {
            event["time"] = json!(TIME);
        }
        text.push_str(&format!("{event}\n"));
    }
    let path = dir.join("journal.jsonl");
    fs::write(&path, text).unwrap();
    path.to_str().unwrap().to_owned()
}

#[test]
fn resource_availability_is_opt_in_for_claims_and_independent_validation() {
    let dir = tempfile::tempdir().unwrap();
    let file = journal(
        dir.path(),
        &[
            task("TS-0001", &["resource:private-file", "os:linux"]),
            task("TS-0002", &[]),
            task("TS-0003", &["resource:private-file"]),
        ],
        &[
            json!({"kind": "claim", "actor": "alice", "task": "TS-0003"}),
            json!({"kind": "submit", "actor": "alice", "task": "TS-0003", "submission": {"pr": 1, "head_sha": SHA, "author": "alice"}}),
        ],
    );
    let base = [
        "next",
        "--journal",
        &file,
        "--actor",
        "pat",
        "--capability",
        "os:linux",
    ];
    let without = output(&base);
    assert_eq!(without["claim"], json!(["TS-0002"]));
    assert_eq!(without["validate"], json!([]));
    assert_eq!(without["mode"], "develop");
    assert_eq!(
        output(&[&base[..], &["--capability", "resource:private-file"]].concat())["claim"],
        json!(["TS-0002"])
    );
    let with = output(&[&base[..], &["--resource", "private-file"]].concat());
    assert_eq!(with["claim"], json!(["TS-0001", "TS-0002"]));
    assert_eq!(with["validate"], json!(["TS-0003"]));
    assert_eq!(with["mode"], "validate");
    let wrong_os = output(&[
        "next",
        "--journal",
        &file,
        "--actor",
        "pat",
        "--capability",
        "os:windows",
        "--resource",
        "private-file",
    ]);
    assert_eq!(wrong_os["claim"], json!(["TS-0002"]));
}

#[test]
fn onboarding_never_requires_a_private_resource_to_join() {
    let dir = tempfile::tempdir().unwrap();
    let root = dir.path().to_str().unwrap();
    let config = dir.path().join(".forgemesh");
    fs::create_dir_all(config.join("tasks")).unwrap();
    assert_eq!(output(&["resources", root]), json!({}));
    fs::write(
        config.join("policy.json"),
        r#"{"swarm":"test","maintainers":["boss"]}"#,
    )
    .unwrap();
    fs::write(
        config.join("tasks/TS-0001.json"),
        task("TS-0001", &["resource:private-file"]).to_string(),
    )
    .unwrap();
    let invalid = run(&["check-config", root]);
    assert!(!invalid.status.success());
    assert!(String::from_utf8_lossy(&invalid.stderr).contains("undeclared resource"));
    let resources = json!({"private-file": "Do you have your own test sample available locally?"});
    fs::write(config.join("resources.json"), resources.to_string()).unwrap();
    assert_eq!(output(&["resources", root]), resources);
    assert!(!run(&["check-config", root]).status.success());
    let mut fallback = task("TS-0002", &[]);
    fallback["execution"] = json!("none");
    fs::write(config.join("tasks/TS-0002.json"), fallback.to_string()).unwrap();
    assert!(run(&["check-config", root]).status.success());
}

#[test]
fn replay_preserves_expiry_and_commit_bound_independent_validation() {
    let dir = tempfile::tempdir().unwrap();
    let file = journal(
        dir.path(),
        &[task("TS-0001", &[]), task("TS-0002", &[])],
        &[
            json!({"kind": "claim", "actor": "alice", "task": "TS-0001"}),
            json!({"kind": "claim", "actor": "pat", "task": "TS-0002"}),
            json!({"kind": "submit", "actor": "alice", "task": "TS-0001", "submission": {"pr": 1, "head_sha": SHA, "author": "alice"}}),
            json!({"kind": "vote", "actor": "bob", "task": "TS-0001", "verdict": "pass", "sha": "aaaaaaa", "evidence": "https://example.org/log"}),
            json!({"kind": "pr_updated", "actor": "@system", "task": "TS-0001", "pr": 1, "head_sha": SHA2}),
            json!({"kind": "vote", "actor": "bob", "task": "TS-0001", "verdict": "pass", "sha": "aaaaaaa", "evidence": "https://example.org/log"}),
            json!({"kind": "vote", "actor": "alice", "task": "TS-0001", "verdict": "pass", "sha": "bbbbbbb", "evidence": "https://example.org/log"}),
        ],
    );
    let state = output(&["status", "--journal", &file]);
    assert_eq!(state["tasks"]["TS-0001"]["status"], "SUBMITTED");
    assert_eq!(state["tasks"]["TS-0001"]["submission"]["head_sha"], SHA2);
    assert_eq!(state["tasks"]["TS-0001"]["votes"], json!({}));
    assert_eq!(state["tasks"]["TS-0002"]["status"], "EXPIRED");
    assert_eq!(
        state["tasks"]["TS-0002"]["attempts"][0]["to"],
        "2026-01-02T00:00:00Z"
    );
}
