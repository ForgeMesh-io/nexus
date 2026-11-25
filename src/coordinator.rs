use crate::{
    core::{SYSTEM, fold, glob_matches, strings, text, time},
    journal::Journal,
};
use anyhow::{Context, Result, bail, ensure};
use chrono::{DateTime, Duration, Utc};
use regex::Regex;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{
    collections::{BTreeMap, BTreeSet, HashMap, HashSet},
    path::Path,
    sync::LazyLock,
};

pub trait Inbox {
    fn comments_since(&self, since: Option<&str>) -> Result<Vec<Value>>;
    fn reply(&self, issue: u64, body: &str) -> Result<()>;
    fn pull(&self, number: u64) -> Result<Option<Value>>;
    fn files(&self, number: u64) -> Result<Vec<String>>;
    fn diff(&self, number: u64) -> Result<String>;
}

const MAX_ATTEMPTS: usize = 8;

fn parse(body: &str) -> Vec<Value> {
    static COMMANDS: LazyLock<Regex> = LazyLock::new(|| {
        Regex::new(concat!(
        r"\A/fm (?P<kind>claim|start|renew|release|submit|vote|approve|block|unblock|reopen|reject|cancel) ",
        r"(?P<task>[A-Z][A-Z0-9]{1,15}-[0-9]{4,})(?P<suffix>.*)\z"
    )).unwrap()
    });
    static VOTE: LazyLock<Regex> = LazyLock::new(|| {
        Regex::new(r"\A (pass|fail) ([0-9a-fA-F]{7,64}) (https://\S{1,500})\z").unwrap()
    });
    static PR: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"\A #([0-9]{1,9})\z").unwrap());
    fn line_event(line: &str) -> Option<Value> {
        let cap = COMMANDS.captures(line)?;
        let kind = &cap["kind"];
        let suffix = &cap["suffix"];
        let mut event = json!({"kind": kind, "task": &cap["task"]});
        match kind {
            "submit" => event["pr"] = json!(PR.captures(suffix)?[1].parse::<u64>().ok()?),
            "vote" => {
                let v = VOTE.captures(suffix)?;
                event["verdict"] = json!(&v[1]);
                event["sha"] = json!(v[2].to_ascii_lowercase());
                event["evidence"] = json!(&v[3]);
            }
            "approve" => {
                let sha = suffix.strip_prefix(' ')?;
                if !(7..=64).contains(&sha.len()) || !sha.bytes().all(|b| b.is_ascii_hexdigit()) {
                    return None;
                }
                event["sha"] = json!(sha.to_ascii_lowercase());
            }
            "block" | "reject" | "cancel" if kind == "block" || !suffix.is_empty() => {
                let reason = suffix.strip_prefix(' ')?;
                if !((if kind == "block" { 5 } else { 1 })..=300).contains(&reason.chars().count())
                {
                    return None;
                }
                event["reason"] = json!(reason);
            }
            _ if !suffix.is_empty() => return None,
            _ => {}
        }
        Some(event)
    }
    body.lines().map(str::trim).filter(|l| *l == "/fm" || l.starts_with("/fm ")).take(5)
        .map(|line| line_event(line).unwrap_or_else(|| json!({"kind": "invalid", "task": null, "line": line.chars().take(200).collect::<String>()}))).collect()
}

fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}

fn patch_id(diff: &str) -> String {
    let mut files: BTreeMap<&str, Vec<String>> = BTreeMap::new();
    let mut name = None;
    for line in diff.lines() {
        if line.starts_with("diff --git ") {
            let file = line.split_once(" b/").map_or(line, |(_, rhs)| rhs);
            files.entry(file).or_default();
            name = Some(file);
        } else if let Some(file) = name
            && line.starts_with(['+', '-'])
            && !line.starts_with("+++")
            && !line.starts_with("---")
        {
            files
                .get_mut(file)
                .unwrap()
                .push(line.chars().filter(|c| !c.is_whitespace()).collect());
        }
    }
    let mut h = Sha256::new();
    for (name, lines) in files {
        h.update(name);
        h.update([0]);
        h.update(lines.join("\n"));
        h.update([0]);
    }
    hex(&h.finalize())
}

fn details(
    inbox: &impl Inbox,
    pr: u64,
    expected: &Value,
    policy: &Value,
) -> Result<(String, BTreeSet<String>)> {
    let protected = strings(&policy["protected_paths"]);
    let violations = inbox
        .files(pr)?
        .into_iter()
        .filter(|file| protected.iter().any(|p| glob_matches(p, file)))
        .collect();
    let patch = patch_id(&inbox.diff(pr)?);
    let current = inbox
        .pull(pr)?
        .context("pull request disappeared while reading its diff")?;
    ensure!(
        ["head", "base", "state", "changed_files"]
            .iter()
            .all(|key| current[*key] == expected[*key]),
        "pull request changed while reading its diff; retry reconciliation"
    );
    Ok((patch, violations))
}

fn head(pr: &Value) -> Result<&str> {
    let sha = text(&pr["head"]["sha"]);
    ensure!(
        sha.len() == 40 && sha.bytes().all(|b| b.is_ascii_hexdigit()),
        "invalid pull request head"
    );
    Ok(sha)
}

fn submission(inbox: &impl Inbox, number: u64, policy: &Value) -> Result<Value> {
    let Some(pr) = inbox.pull(number)? else {
        return Ok(json!({"error": format!("pull request #{number} not found")}));
    };
    if pr["state"] != "open" {
        return Ok(json!({"error": format!("pull request #{number} is not open")}));
    }
    let (patch, violations) = details(inbox, number, &pr, policy)?;
    Ok(
        json!({"pr": number, "head_sha": head(&pr)?, "author": pr["user"]["login"], "patch_id": patch, "violations": violations}),
    )
}

fn config_events(
    events: &[Value],
    policy: &Value,
    tasks: &[Value],
    now: &str,
) -> Result<Vec<Value>> {
    let mut current_policy = &Value::Null;
    let mut current_tasks = HashMap::new();
    for ev in events {
        match text(&ev["kind"]) {
            "policy" => current_policy = &ev["policy"],
            "task" => {
                current_tasks.insert(text(&ev["task"]["id"]), &ev["task"]);
            }
            _ => {}
        }
    }
    let digest = |value: &Value| -> Result<String> {
        Ok(hex(&Sha256::digest(serde_json::to_vec(value)?)[..8]))
    };
    let mut new = vec![];
    let offset = events.len();
    if policy != current_policy {
        new.push(json!({"kind": "policy", "id": format!("cfg:policy:{}:{offset}", digest(policy)?), "actor": SYSTEM, "time": now, "policy": policy}));
    }
    for task in tasks {
        let id = text(&task["id"]);
        if current_tasks.get(id).copied() != Some(task) {
            new.push(json!({"kind": "task", "id": format!("cfg:task:{id}:{}:{offset}", digest(task)?), "actor": SYSTEM, "time": now, "task": task}));
        }
    }
    Ok(new)
}

fn collect_comments(
    inbox: &impl Inbox,
    policy: &Value,
    events: &mut Vec<Value>,
    cursor: &mut Value,
    full_scan: bool,
) -> Result<()> {
    let previous = cursor["comments_since"].as_str();
    let since = match previous.filter(|_| !full_scan) {
        Some(s) => Some(time(s.parse::<DateTime<Utc>>()? - Duration::minutes(10))),
        None => None,
    };
    let mut newest = if full_scan {
        None
    } else {
        previous.map(str::to_owned)
    };
    let mut seen: HashSet<_> = events.iter().map(|v| text(&v["id"]).to_owned()).collect();
    for c in inbox.comments_since(since.as_deref())? {
        let at = c["created_at"]
            .as_str()
            .context("missing comment creation time")?;
        if newest.as_deref().is_none_or(|seen| at > seen) {
            newest = Some(at.into());
        }
        let actor = text(&c["user"]["login"]);
        let body = text(&c["body"]);
        if c["user"]["type"] == "Bot" || !body.contains("/fm") {
            continue;
        }
        ensure!(
            !actor.is_empty() && actor != SYSTEM,
            "invalid comment actor"
        );
        let comment_id = c["id"].as_u64().context("missing comment ID")?;
        let issue: u64 = text(&c["issue_url"])
            .rsplit('/')
            .next()
            .unwrap_or_default()
            .parse()
            .context("invalid issue number")?;
        for (i, mut cmd) in parse(body).into_iter().enumerate() {
            let id = format!("c:{comment_id}:{i}");
            if !seen.insert(id.clone()) {
                continue;
            }
            if cmd["kind"] == "submit" {
                let pr = cmd.as_object_mut().unwrap().remove("pr").unwrap();
                cmd["submission"] = submission(inbox, pr.as_u64().unwrap(), policy)?;
            }
            for (k, v) in [
                ("id", json!(id)),
                ("actor", json!(actor)),
                ("issue", json!(issue)),
                ("time", json!(at)),
                ("url", c["html_url"].clone()),
            ] {
                cmd[k] = v;
            }
            events.push(cmd);
        }
    }
    if let Some(newest) = newest {
        cursor["comments_since"] = json!(newest);
    }
    Ok(())
}

fn collect_pulls(
    inbox: &impl Inbox,
    policy: &Value,
    events: &mut Vec<Value>,
    now: &str,
) -> Result<()> {
    let state = fold(events, None)?;
    for (id, task) in &state.tasks {
        if !task.status.review() || task.submission.is_null() {
            continue;
        }
        let number = task.submission["pr"]
            .as_u64()
            .context("invalid submission PR")?;
        let Some(pr) = inbox.pull(number)? else {
            continue;
        };
        let sha = head(&pr)?;
        let previous = text(&task.submission["head_sha"]);
        let mut event = json!({"actor": SYSTEM, "time": now, "task": id, "pr": number});
        let kind = if pr["merged"] == true {
            event["head_sha"] = json!(sha);
            "merged"
        } else if pr["state"] == "closed" {
            "pr_closed"
        } else if sha != previous {
            let (patch, violations) = details(inbox, number, &pr, policy)?;
            event["head_sha"] = json!(sha);
            event["patch_id"] = json!(patch);
            event["violations"] = json!(violations);
            "pr_updated"
        } else {
            continue;
        };
        // A force-push can return to a previously seen SHA. Deduplicate by current state, not by SHA history.
        event["kind"] = json!(kind);
        event["id"] = json!(format!("pr:{number}:{kind}:{id}:{}", events.len()));
        events.push(event);
    }
    Ok(())
}

pub fn run(
    inbox: &impl Inbox,
    state_dir: &Path,
    policy: &Value,
    tasks: &[Value],
    full_scan: bool,
    now: DateTime<Utc>,
) -> Result<Value> {
    let clock = time(now);
    for attempt in 1..=MAX_ATTEMPTS {
        let journal = Journal::fetch(state_dir)?;
        let mut events = journal.events.clone();
        events.extend(config_events(&events, policy, tasks, &clock)?);
        let mut cursor = journal.cursor.clone();
        collect_comments(inbox, policy, &mut events, &mut cursor, full_scan)?;
        collect_pulls(inbox, policy, &mut events, &clock)?;
        cursor["last_run"] = json!(&clock);
        let appended = events.len() - journal.events.len();
        if !journal.publish(
            &events,
            &cursor,
            now,
            &format!("Ingest {appended} event(s)"),
        )? {
            continue;
        }
        let decisions = fold(&events, Some(now))?.decisions;
        let start = cursor["replied"].as_u64().unwrap_or_default() as usize;
        ensure!(
            start <= decisions.len(),
            "reply cursor exceeds decision count"
        );
        let mut replied = 0;
        for d in &decisions[start..] {
            if let Some(issue) = d["issue"].as_u64().filter(|n| *n > 0) {
                let mark = if d["accepted"] == true { "✅" } else { "❌" };
                inbox.reply(
                    issue,
                    &format!(
                        "{mark} `{}` {} by @{}: {}\n\n<!-- fm:{} -->",
                        text(&d["kind"]),
                        text(&d["task"]),
                        text(&d["actor"]),
                        text(&d["message"]),
                        text(&d["event"])
                    ),
                )?;
                replied += 1;
            }
        }
        if start != decisions.len() {
            for _ in 0..MAX_ATTEMPTS {
                let latest = Journal::fetch(state_dir)?;
                let mut cursor = latest.cursor.clone();
                let recorded = cursor["replied"].as_u64().unwrap_or_default();
                let next = decisions.len() as u64;
                if recorded >= next {
                    break;
                }
                cursor["replied"] = json!(next);
                let at = cursor["last_run"]
                    .as_str()
                    .unwrap_or(&clock)
                    .parse::<DateTime<Utc>>()?
                    .max(now);
                if latest.publish(&latest.events, &cursor, at, "Record replies")? {
                    break;
                }
            }
        }
        return Ok(json!({"appended": appended, "replied": replied, "attempts": attempt}));
    }
    bail!("could not publish the journal after several attempts")
}
