use serde_json::{Value, json};
use std::{fs, os::unix::fs::PermissionsExt, path::Path, process::Command};

const IMAGE: &str = "ghcr.io/forgemesh-io/nexus@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";

fn git(source: &Path, args: &[&str]) -> String {
    let out = Command::new("git")
        .current_dir(source)
        .args(args)
        .output()
        .unwrap();
    assert!(
        out.status.success(),
        "{}",
        String::from_utf8_lossy(&out.stderr)
    );
    String::from_utf8(out.stdout).unwrap().trim().to_owned()
}

#[test]
fn sandbox_uses_an_isolated_copy_and_attest_uses_the_reported_commit() {
    let tmp = tempfile::tempdir().unwrap();
    let source = tmp.path().join("source");
    fs::create_dir(&source).unwrap();
    git(&source, &["init", "-q"]);
    fs::write(source.join("tracked"), "committed\n").unwrap();
    git(&source, &["add", "tracked"]);
    git(
        &source,
        &[
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.org",
            "-c",
            "commit.gpgSign=false",
            "commit",
            "-qm",
            "Fixture",
        ],
    );
    let sha = git(&source, &["rev-parse", "HEAD"]);
    fs::write(source.join("tracked"), "modified\n").unwrap();
    fs::write(source.join(".env"), "private dummy value").unwrap();
    let fake = tmp.path().join("docker");
    fs::write(&fake, r#"#!/bin/sh
set -eu
for flag in '--network none' '--cap-drop ALL' '--security-opt no-new-privileges' '--read-only' '--user 1000:1000'; do
  case " $* " in *" $flag "*) ;; *) echo "missing $flag" >&2; exit 80;; esac
done
for arg; do
  case "$arg" in type=bind,src=*,dst=/work) ws=${arg#type=bind,src=}; ws=${ws%,dst=/work};; esac
  last=$arg
done
test ! -e "$ws/.git"
test ! -e "$ws/.env"
if [ "$last" != expect-committed ]; then
  test "$(cat "$ws/tracked")" = modified
else
  test "$(cat "$ws/tracked")" = committed
fi
echo 'sandbox output'
"#).unwrap();
    fs::set_permissions(&fake, fs::Permissions::from_mode(0o755)).unwrap();
    let run = |args: &[&str]| {
        Command::new(env!("CARGO_BIN_EXE_forgemesh"))
            .env(
                "PATH",
                format!(
                    "{}:{}",
                    tmp.path().display(),
                    std::env::var("PATH").unwrap()
                ),
            )
            .args(args)
            .output()
            .unwrap()
    };
    let source = source.to_str().unwrap();
    let result = run(&[
        "sandbox", "--image", IMAGE, "--source", source, "--", "echo", "-n",
    ]);
    assert!(
        result.status.success(),
        "{}",
        String::from_utf8_lossy(&result.stderr)
    );
    assert_eq!(result.stdout, b"sandbox output\n");
    assert!(
        !run(&[
            "sandbox",
            "--image",
            "untrusted:latest",
            "--source",
            source,
            "--",
            "echo"
        ])
        .status
        .success()
    );
    let task = tmp.path().join("task.json");
    let definition = json!({"id":"TS-0001","swarm":"test","title":"Example test","objective":"Check the committed tree","type":"research","priority":1,"risk":"low","acceptance":["Report test evidence"],"validation":{"commands":["expect-committed"]}});
    fs::write(&task, definition.to_string()).unwrap();
    let attest = || {
        run(&[
            "attest",
            "--image",
            IMAGE,
            "--source",
            source,
            "--task-file",
            task.to_str().unwrap(),
        ])
    };
    let result = attest();
    assert!(
        result.status.success(),
        "{}\n{}",
        String::from_utf8_lossy(&result.stderr),
        String::from_utf8_lossy(&result.stdout)
    );
    let report: Value = serde_json::from_slice(&result.stdout).unwrap();
    assert_eq!(report["subject"][0]["digest"]["gitCommit"], sha);
    assert_eq!(report["predicate"]["passed"], true);
    assert!(!String::from_utf8_lossy(&result.stdout).contains("sandbox output"));
    let mut native = definition;
    native["execution"] = json!("native");
    fs::write(&task, native.to_string()).unwrap();
    assert!(!attest().status.success());
}
