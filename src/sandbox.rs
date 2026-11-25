use anyhow::{Context, Result, ensure};
use clap::Args;
use forgemesh::{config, core};
use regex::Regex;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{
    ffi::OsString,
    fs,
    path::{Path, PathBuf},
    process::{Command, Output},
    sync::LazyLock,
};

#[derive(Args)]
pub struct Limits {
    #[arg(long, default_value_t = 2.)]
    cpus: f64,
    #[arg(long, default_value = "4g")]
    memory: String,
    #[arg(long, default_value_t = 3600)]
    timeout: u64,
    /// Explicitly allow access to Linux DRM render nodes for this run.
    #[arg(long)]
    gpu: bool,
}

fn copy(source: &Path, dest: &Path) -> Result<()> {
    #[cfg(unix)]
    use std::os::unix::fs::{PermissionsExt, symlink};

    fs::create_dir(dest)?;
    for entry in fs::read_dir(source)? {
        let entry = entry?;
        let name = entry.file_name();
        let label = name.to_string_lossy();
        if matches!(
            label.as_ref(),
            ".git" | ".venv" | ".env" | ".ssh" | ".gnupg" | ".aws" | "__pycache__"
        ) || label.starts_with(".env.")
            || label.ends_with(".pem")
            || label.ends_with(".key")
        {
            continue;
        }
        let from = entry.path();
        let to = dest.join(name);
        let kind = entry.file_type()?;
        if kind.is_dir() {
            copy(&from, &to)?;
        } else if kind.is_file() {
            fs::copy(&from, &to)?;
            #[cfg(unix)]
            fs::set_permissions(
                &to,
                fs::Permissions::from_mode(
                    0o666 | (entry.metadata()?.permissions().mode() & 0o111),
                ),
            )?;
        } else if kind.is_symlink() {
            #[cfg(unix)]
            symlink(fs::read_link(&from)?, &to)?;
        }
    }
    #[cfg(unix)]
    fs::set_permissions(dest, fs::Permissions::from_mode(0o777))?;
    Ok(())
}

fn checked_source(source: &Path) -> Result<PathBuf> {
    ensure!(
        cfg!(target_os = "linux"),
        "sandbox execution currently requires Linux"
    );
    let source = source
        .canonicalize()
        .context("resolving source directory")?;
    let home = std::env::home_dir()
        .context("could not identify the home directory")?
        .canonicalize()?;
    ensure!(
        source.is_dir() && !home.starts_with(&source),
        "pass a project directory, not the home directory or an ancestor"
    );
    Ok(source)
}

fn run(image: &str, source: &Path, command: &[OsString], limits: &Limits) -> Result<Output> {
    static DIGEST: LazyLock<Regex> = LazyLock::new(|| {
        Regex::new(r"\A[a-z0-9][a-z0-9._/-]*(?::[0-9]+/[a-z0-9._/-]+)?(?::[a-zA-Z0-9_.-]+)?@sha256:[0-9a-f]{64}\z").unwrap()
    });
    static MEMORY: LazyLock<Regex> =
        LazyLock::new(|| Regex::new(r"\A[1-9][0-9]*[bkmg]?\z").unwrap());
    ensure!(
        DIGEST.is_match(image),
        "image must be pinned by digest: name@sha256:<64 hex>"
    );
    ensure!(
        limits.cpus.is_finite()
            && limits.cpus > 0.
            && limits.timeout > 0
            && MEMORY.is_match(&limits.memory),
        "invalid sandbox limits"
    );
    let source = checked_source(source)?;
    let temp = tempfile::Builder::new().prefix("forgemesh-ws-").tempdir()?;
    let workspace = temp.path().join("work");
    copy(&source, &workspace).context("copying disposable workspace")?;
    let path = workspace.to_str().context("workspace path is not UTF-8")?;
    ensure!(
        !path.contains([',', '"', '\n', '\r']),
        "unsupported temporary workspace path"
    );

    let mut docker = Command::new("docker");
    docker.args([
        "run",
        "--rm",
        "--init",
        "--pull",
        "never",
        "--network",
        "none",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--read-only",
        "--tmpfs",
        "/tmp:rw,nosuid,size=2g",
        "--tmpfs",
        "/home/forge:rw,nosuid,size=1g",
        "--user",
        "1000:1000",
        "--cpus",
        &limits.cpus.to_string(),
        "--memory",
        &limits.memory,
        "--memory-swap",
        &limits.memory,
        "--pids-limit",
        "512",
        "--stop-timeout",
        "10",
        "--env",
        "HOME=/home/forge",
        "--workdir",
        "/work",
        "--mount",
        &format!("type=bind,src={path},dst=/work"),
    ]);
    if limits.gpu {
        let mut nodes = vec![];
        for entry in fs::read_dir("/dev/dri").context("opening DRM devices")? {
            let entry = entry?;
            if entry
                .file_name()
                .to_str()
                .and_then(|s| s.strip_prefix("renderD"))
                .is_some_and(|n| n.parse::<u32>().is_ok())
            {
                nodes.push(entry.path());
            }
        }
        ensure!(!nodes.is_empty(), "no DRM render nodes available");
        for node in nodes {
            #[cfg(unix)]
            {
                use std::os::unix::fs::MetadataExt;
                docker
                    .arg("--group-add")
                    .arg(node.metadata()?.gid().to_string());
            }
            docker.arg("--device").arg(node);
        }
    }
    docker
        .args([
            "--entrypoint",
            "timeout",
            image,
            "-k",
            "10",
            &limits.timeout.to_string(),
        ])
        .args(command)
        .output()
        .context("running Docker sandbox")
}

pub fn execute(image: &str, source: &Path, command: &[OsString], limits: &Limits) -> Result<i32> {
    use std::io::{Write, stderr, stdout};
    let output = run(image, source, command, limits)?;
    stdout().lock().write_all(&output.stdout)?;
    stderr().lock().write_all(&output.stderr)?;
    Ok(output.status.code().unwrap_or(1))
}

pub fn attest(task_file: &Path, source: &Path, image: Option<&str>, gpu: bool) -> Result<Value> {
    let task = config::task(task_file)?;
    ensure!(
        task.get("execution").is_none_or(|v| v == "container"),
        "only container tasks are automated"
    );
    let gpu_task = matches!(task["profile"].as_str(), Some("gpu" | "gameplay"));
    ensure!(
        !gpu_task || gpu,
        "GPU validation requires explicit --gpu approval"
    );
    let commands = core::strings(&task["validation"]["commands"]);
    ensure!(!commands.is_empty(), "no validation commands declared");
    let image = image
        .or(task["validation"]["image"].as_str())
        .context("no validation image specified")?;
    let source = checked_source(source)?;
    let head = Command::new("git")
        .current_dir(&source)
        .args(["rev-parse", "--verify", "HEAD^{commit}"])
        .output()?;
    ensure!(head.status.success(), "could not resolve the source commit");
    let sha = std::str::from_utf8(&head.stdout)?.trim();
    ensure!(
        matches!(sha.len(), 40 | 64) && sha.bytes().all(|b| b.is_ascii_hexdigit()),
        "invalid source commit"
    );
    let stage = tempfile::tempdir()?;
    let archive = stage.path().join("source.tar");
    let checkout = stage.path().join("checkout");
    fs::create_dir(&checkout)?;
    // shortcut: git archive excludes submodules; use a pinned recursive checkout when a task needs them.
    ensure!(
        Command::new("git")
            .current_dir(&source)
            .args(["archive", "--format=tar", "--output"])
            .arg(&archive)
            .arg(sha)
            .status()?
            .success(),
        "could not archive the source commit"
    );
    ensure!(
        Command::new("tar")
            .current_dir(&checkout)
            .args(["--no-same-owner", "--no-same-permissions", "-xf"])
            .arg(&archive)
            .status()?
            .success(),
        "could not unpack the source commit"
    );
    let limits = Limits {
        cpus: 2.,
        memory: "4g".into(),
        timeout: 3600,
        gpu: gpu && gpu_task,
    };
    let mut results = vec![];
    for cmd in commands {
        let output = run(
            image,
            &checkout,
            &["sh".into(), "-c".into(), cmd.into()],
            &limits,
        )?;
        let mut hash = Sha256::new();
        hash.update(output.stdout);
        hash.update(output.stderr);
        let digest: String = hash.finalize().iter().map(|b| format!("{b:02x}")).collect();
        results.push(
            json!({"command": cmd, "exit_code": output.status.code().unwrap_or(1),
            "passed": output.status.success(), "log_sha256": digest, "log_tail": ""}),
        );
    }
    let passed = results.iter().all(|r| r["passed"] == true);
    let caps = crate::capabilities::detect();
    let gpus: Vec<_> = caps["gpus"]
        .as_array()
        .into_iter()
        .flatten()
        .map(|g| &g["name"])
        .collect();
    Ok(json!({"_type": "https://in-toto.io/Statement/v1",
        "subject": [{"name": "git-commit", "digest": {"gitCommit": sha}}],
        "predicateType": "https://forgemesh-io.github.io/registry/attestation/test-result/v1",
        "predicate": {"task": task["id"], "image": image, "mode": "container", "results": results,
            "passed": passed, "finished_at": core::time(chrono::Utc::now()),
            "environment": {"os": "Linux", "arch": std::env::consts::ARCH, "tags": caps["tags"], "gpus": gpus}}}))
}
