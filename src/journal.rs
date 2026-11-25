use anyhow::{Context, Result, bail, ensure};
use chrono::{DateTime, Utc};
use serde_json::{Value, json};
use std::{
    io::Write,
    path::Path,
    process::{Command, Output, Stdio},
};

const BRANCH: &str = "refs/heads/forgemesh-state";

pub fn parse(text: &str) -> Result<Vec<Value>> {
    text.lines()
        .enumerate()
        .filter(|(_, line)| !line.trim().is_empty())
        .map(|(i, line)| {
            serde_json::from_str(line).with_context(|| format!("reading journal line {}", i + 1))
        })
        .collect()
}

pub struct Journal<'a> {
    dir: &'a Path,
    parent: Option<String>,
    pub events: Vec<Value>,
    pub cursor: Value,
}

fn git(dir: &Path, args: &[&str], input: Option<&[u8]>) -> Result<Output> {
    let mut child = Command::new("git")
        .current_dir(dir)
        .args(args)
        .env("GIT_TERMINAL_PROMPT", "0")
        .stdin(if input.is_some() {
            Stdio::piped()
        } else {
            Stdio::null()
        })
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .context("starting git")?;
    if let Some(input) = input {
        child
            .stdin
            .take()
            .context("opening git stdin")?
            .write_all(input)?;
    }
    Ok(child.wait_with_output()?)
}

fn checked(dir: &Path, args: &[&str], input: Option<&[u8]>) -> Result<String> {
    let output = git(dir, args, input)?;
    // A remote URL can include credentials: never forward raw Git diagnostics.
    ensure!(
        output.status.success(),
        "git {} failed ({})",
        args[0],
        output.status
    );
    Ok(String::from_utf8(output.stdout)?)
}

impl<'a> Journal<'a> {
    pub fn fetch(dir: &'a Path) -> Result<Self> {
        let probe = git(dir, &["ls-remote", "--exit-code", "origin", BRANCH], None)?;
        if probe.status.code() == Some(2) {
            return Ok(Self {
                dir,
                parent: None,
                events: vec![],
                cursor: json!({}),
            });
        }
        ensure!(probe.status.success(), "could not read remote state branch");
        checked(
            dir,
            &[
                "fetch",
                "--quiet",
                "--no-tags",
                "--no-recurse-submodules",
                "origin",
                BRANCH,
            ],
            None,
        )?;
        let parent = checked(dir, &["rev-parse", "--verify", "FETCH_HEAD^{commit}"], None)?
            .trim()
            .to_owned();
        let read = |name: &str| checked(dir, &["show", &format!("{parent}:{name}")], None);
        let events = parse(&read("journal.jsonl")?)?;
        let cursor = serde_json::from_str::<Value>(&read("cursor.json")?)?;
        ensure!(cursor.is_object(), "invalid state cursor");
        Ok(Self {
            dir,
            parent: Some(parent),
            events,
            cursor,
        })
    }

    pub fn publish(
        &self,
        events: &[Value],
        cursor: &Value,
        now: DateTime<Utc>,
        message: &str,
    ) -> Result<bool> {
        ensure!(events.starts_with(&self.events), "journal is append-only");
        let state = crate::core::fold(events, Some(now))?;
        let mut snapshot = state.snapshot();
        snapshot["version"] = json!(1);
        let jsonl = |values: &[Value]| -> Result<String> {
            let mut out = String::new();
            for value in values {
                out.push_str(&serde_json::to_string(value)?);
                out.push('\n');
            }
            Ok(out)
        };
        let mut tree = String::new();
        for (name, content) in [
            ("journal.jsonl", jsonl(events)?),
            (
                "state.json",
                serde_json::to_string_pretty(&snapshot)? + "\n",
            ),
            ("decisions.jsonl", jsonl(&state.decisions)?),
            ("cursor.json", serde_json::to_string_pretty(cursor)? + "\n"),
        ] {
            let id = checked(
                self.dir,
                &["hash-object", "-w", "--stdin"],
                Some(content.as_bytes()),
            )?;
            tree.push_str(&format!("100644 blob {}\t{name}\n", id.trim()));
        }
        let id = checked(self.dir, &["mktree"], Some(tree.as_bytes()))?;
        let id = id.trim();
        let mut args = vec![
            "-c",
            "user.name=github-actions[bot]",
            "-c",
            "user.email=41898282+github-actions[bot]@users.noreply.github.com",
            "-c",
            "commit.gpgSign=false",
            "commit-tree",
            id,
            "-m",
            message,
        ];
        if let Some(parent) = &self.parent {
            let old_tree = checked(
                self.dir,
                &["rev-parse", &format!("{parent}^{{tree}}")],
                None,
            )?;
            if old_tree.trim() == id {
                return Ok(true);
            }
            args.extend(["-p", parent]);
        }
        let commit = checked(self.dir, &args, None)?;
        let output = git(
            self.dir,
            &[
                "push",
                "--porcelain",
                "origin",
                &format!("{}:{BRANCH}", commit.trim()),
            ],
            None,
        )?;
        if output.status.success() {
            return Ok(true);
        }
        let current = git(
            self.dir,
            &["ls-remote", "--exit-code", "origin", BRANCH],
            None,
        )?;
        let advertised = std::str::from_utf8(&current.stdout)?
            .split_whitespace()
            .next();
        if current.status.success() && advertised.is_some() && advertised != self.parent.as_deref()
        {
            return Ok(false);
        }
        bail!("git push of state branch failed ({})", output.status)
    }
}
