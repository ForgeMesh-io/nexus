use anyhow::{Context, Result, bail, ensure};
use chrono::{DateTime, Duration, SecondsFormat, Utc};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::collections::{BTreeMap, HashMap, HashSet};

type Clock = DateTime<Utc>;
pub const SYSTEM: &str = "@system";
pub fn time(t: Clock) -> String {
    t.to_rfc3339_opts(SecondsFormat::Secs, true)
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(rename_all = "lowercase")]
pub enum Risk {
    Low,
    Medium,
    High,
    Critical,
    Never,
}

#[derive(Debug, Deserialize)]
#[serde(default)]
pub struct Passes {
    low: u64,
    medium: u64,
    high: u64,
    critical: u64,
}

impl Default for Passes {
    fn default() -> Self {
        Self {
            low: 1,
            medium: 2,
            high: 2,
            critical: 3,
        }
    }
}

#[derive(Debug, Deserialize)]
#[serde(default)]
pub struct Pressure {
    pub low_queue: usize,
    pub high_queue: usize,
    pub dev_share_low: f64,
    pub dev_share_mid: f64,
    pub dev_share_high: f64,
}

impl Default for Pressure {
    fn default() -> Self {
        Self {
            low_queue: 3,
            high_queue: 10,
            dev_share_low: 0.7,
            dev_share_mid: 0.35,
            dev_share_high: 0.05,
        }
    }
}

#[derive(Debug, Deserialize)]
#[serde(default)]
pub struct Policy {
    pub paused: bool,
    lease_hours: f64,
    max_renewals: u64,
    max_active_claims_per_user: u64,
    pub wip_limit_per_component: u64,
    required_passes: Passes,
    maintainer_approval_from: Risk,
    trusted_vote_from: Risk,
    maintainers: Vec<String>,
    trusted_validators: Vec<String>,
    pub validation_pressure: Pressure,
}

impl Default for Policy {
    fn default() -> Self {
        Self {
            paused: false,
            lease_hours: 24.,
            max_renewals: 6,
            max_active_claims_per_user: 2,
            wip_limit_per_component: 3,
            required_passes: Passes::default(),
            maintainer_approval_from: Risk::High,
            trusted_vote_from: Risk::High,
            maintainers: vec![],
            trusted_validators: vec![],
            validation_pressure: Pressure::default(),
        }
    }
}

#[derive(Debug, Deserialize)]
pub struct Definition {
    pub id: String,
    #[serde(rename = "type")]
    pub kind: String,
    pub priority: u8,
    risk: Risk,
    #[serde(default)]
    pub depends_on: Vec<String>,
    #[serde(default)]
    pub components: Vec<String>,
    #[serde(default)]
    pub hardware: Vec<String>,
    #[serde(default)]
    files: Vec<String>,
    parallel_group: Option<String>,
    lease_hours: Option<f64>,
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq, Serialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum Status {
    #[default]
    Available,
    Claimed,
    InProgress,
    Submitted,
    Validating,
    ChangesRequested,
    ReadyToMerge,
    Merged,
    Rejected,
    Blocked,
    Expired,
    Cancelled,
}
use Status::*;

impl Status {
    pub fn claimable(self) -> bool {
        matches!(self, Available | Expired)
    }
    fn leased(self) -> bool {
        matches!(self, Claimed | InProgress | ChangesRequested)
    }
    pub fn review(self) -> bool {
        matches!(self, Submitted | Validating | ReadyToMerge)
    }
    pub fn waiting(self) -> bool {
        matches!(self, Submitted | Validating)
    }
    fn active(self) -> bool {
        self.leased() || self.review()
    }
    fn terminal(self) -> bool {
        matches!(self, Merged | Rejected | Cancelled)
    }
}

impl std::fmt::Display for Status {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(json!(self).as_str().unwrap())
    }
}

pub struct Task {
    pub raw: Value,
    pub definition: Definition,
    pub status: Status,
    pub claimant: Option<String>,
    lease_expires: Option<Clock>,
    renewals: u64,
    pub submission: Value,
    pub votes: BTreeMap<String, Value>,
    approval: Value,
    attempts: Vec<Value>,
    block_reason: Value,
}

impl Task {
    fn new(raw: Value, definition: Definition) -> Self {
        Self {
            raw,
            definition,
            status: Available,
            claimant: None,
            lease_expires: None,
            renewals: 0,
            submission: Value::Null,
            votes: BTreeMap::new(),
            approval: Value::Null,
            attempts: vec![],
            block_reason: Value::Null,
        }
    }

    fn end_attempt(&mut self, at: Clock, outcome: &str) {
        if let Some(attempt) = self.attempts.last_mut().filter(|a| a["to"].is_null()) {
            attempt["to"] = json!(time(at));
            attempt["outcome"] = json!(outcome);
        }
    }
}

#[derive(Default)]
pub struct State {
    pub policy: Policy,
    pub tasks: BTreeMap<String, Task>,
    pub clock: Option<Clock>,
    pub decisions: Vec<Value>,
    seen: HashSet<String>,
    patches: HashMap<String, String>,
}

pub fn glob_matches(pattern: &str, path: &str) -> bool {
    // Match Python's fnmatchcase: consecutive stars have no special path semantics.
    let mut normal = String::with_capacity(pattern.len());
    for ch in pattern.chars() {
        if ch != '*' || !normal.ends_with('*') {
            normal.push(ch);
        }
    }
    glob::Pattern::new(&normal).map_or(pattern == path, |p| p.matches(path))
}

fn overlap(a: &str, b: &str) -> bool {
    let prefix = |s: &str| s.find(['*', '?', '[']).unwrap_or(s.len());
    glob_matches(a, b)
        || glob_matches(b, a)
        || (prefix(a) < a.len() && b[..prefix(b)].starts_with(&a[..prefix(a)]))
        || (prefix(b) < b.len() && a[..prefix(a)].starts_with(&b[..prefix(b)]))
}

impl State {
    fn missing<'a>(&self, task: &'a Task) -> Vec<&'a str> {
        task.definition
            .depends_on
            .iter()
            .filter(|id| !self.tasks.get(*id).is_some_and(|t| t.status == Merged))
            .map(String::as_str)
            .collect()
    }

    pub fn display_status(&self, task: &Task) -> Status {
        if task.status.claimable() && !self.missing(task).is_empty() {
            Blocked
        } else {
            task.status
        }
    }

    pub fn conflicts(&self, task: &Task) -> Vec<&str> {
        let d = &task.definition;
        self.tasks
            .values()
            .filter(|other| {
                let od = &other.definition;
                od.id != d.id
                    && other.status.active()
                    && !(d.parallel_group.as_ref().is_some_and(|g| !g.is_empty())
                        && d.parallel_group == od.parallel_group)
                    && d.files
                        .iter()
                        .any(|a| od.files.iter().any(|b| overlap(a, b)))
            })
            .map(|t| t.definition.id.as_str())
            .collect()
    }

    pub fn component_load(&self, component: &str) -> u64 {
        self.tasks
            .values()
            .filter(|t| t.status.active() && t.definition.components.iter().any(|c| c == component))
            .count() as u64
    }

    pub fn snapshot(&self) -> Value {
        let tasks: BTreeMap<_, _> = self.tasks.iter().map(|(id, t)| (id, json!({
            "id": id, "status": t.status, "display_status": self.display_status(t),
            "claimant": t.claimant, "lease_expires": t.lease_expires.map(time), "renewals": t.renewals,
            "submission": t.submission, "votes": t.votes, "approval": t.approval,
            "attempts": t.attempts, "block_reason": t.block_reason,
        }))).collect();
        json!({"clock": self.clock.map(time), "paused": self.policy.paused, "tasks": tasks})
    }

    fn advance(&mut self, at: Clock) {
        let now = at.max(self.clock.unwrap_or(at));
        self.clock = Some(now);
        for task in self.tasks.values_mut().filter(|t| t.status.leased()) {
            if let Some(expiry) = task.lease_expires.filter(|e| *e <= now) {
                task.end_attempt(expiry, "expired");
                task.status = Expired;
                task.claimant = None;
                task.lease_expires = None;
                task.renewals = 0;
            }
        }
    }

    fn lease(&self, task: &Task, now: Clock) -> Result<Clock> {
        let hours = task
            .definition
            .lease_hours
            .unwrap_or(self.policy.lease_hours);
        ensure!((1.0..=168.).contains(&hours), "invalid lease duration");
        now.checked_add_signed(Duration::microseconds(
            (hours * 3_600_000_000.).round_ties_even() as i64,
        ))
        .context("lease exceeds clock range")
    }

    fn maintainer(&self, actor: &str) -> bool {
        actor == SYSTEM || self.policy.maintainers.iter().any(|m| m == actor)
    }

    fn trusted(&self, actor: &str) -> bool {
        self.maintainer(actor) || self.policy.trusted_validators.iter().any(|m| m == actor)
    }

    fn evaluate(&self, task: &mut Task, now: Clock) -> Result<String> {
        let sha = &task.submission["head_sha"];
        let by_verdict = |verdict| {
            task.votes
                .iter()
                .filter(|(_, v)| &v["sha"] == sha && v["verdict"] == verdict)
                .map(|(actor, _)| actor)
                .collect::<Vec<_>>()
        };
        let risk = task.definition.risk;
        let req = &self.policy.required_passes;
        let needed = match risk {
            Risk::Low => req.low,
            Risk::Medium => req.medium,
            Risk::High => req.high,
            Risk::Critical => req.critical,
            Risk::Never => bail!("invalid task risk"),
        };
        let fails = by_verdict("fail");
        if fails.iter().any(|v| self.trusted(v)) || fails.len() as u64 >= needed {
            task.lease_expires = Some(self.lease(task, now)?);
            task.status = ChangesRequested;
            return Ok(format!(
                "changes requested by validators: {}",
                fails
                    .iter()
                    .map(|v| format!("@{v}"))
                    .collect::<Vec<_>>()
                    .join(", ")
            ));
        }
        let passes = by_verdict("pass");
        let mut missing = vec![];
        if needed > passes.len() as u64 {
            missing.push(format!(
                "{} more independent pass vote(s)",
                needed - passes.len() as u64
            ));
        }
        if risk >= self.policy.trusted_vote_from && !passes.iter().any(|v| self.trusted(v)) {
            missing.push("a pass from a trusted validator".into());
        }
        if (risk >= self.policy.maintainer_approval_from
            || !strings(&task.submission["violations"]).is_empty())
            && &task.approval["sha"] != sha
        {
            missing.push("maintainer approval".into());
        }
        task.status = if missing.is_empty() {
            ReadyToMerge
        } else {
            Validating
        };
        Ok(if missing.is_empty() {
            "ready to merge".into()
        } else {
            format!("still needs {}", missing.join(", "))
        })
    }

    fn transition(&mut self, task: &mut Task, ev: &Value, now: Clock) -> Result<String> {
        let actor = text(&ev["actor"]);
        let claimant = task.claimant.as_deref();
        let status = task.status;
        let kind = text(&ev["kind"]);
        if matches!(kind, "start" | "renew" | "submit") && claimant != Some(actor) {
            bail!(
                "{}",
                claimant.map_or_else(
                    || "task is not claimed".to_owned(),
                    |c| format!("only the claimant (@{c}) can do this")
                )
            );
        }
        let msg = match kind {
            "claim" => {
                ensure!(!self.policy.paused, "swarm is paused, no new claims");
                ensure!(
                    status.claimable(),
                    "task is {status}{}",
                    claimant
                        .map(|c| format!(" (claimed by @{c})"))
                        .unwrap_or_default()
                );
                let missing = self.missing(task);
                ensure!(
                    missing.is_empty(),
                    "blocked by unfinished dependencies: {}",
                    missing.join(", ")
                );
                let active = self
                    .tasks
                    .values()
                    .filter(|t| t.claimant.as_deref() == Some(actor) && t.status.leased())
                    .count() as u64;
                let limit = self.policy.max_active_claims_per_user;
                ensure!(
                    active < limit,
                    "@{actor} already holds {active} active claims (limit {limit})"
                );
                for c in &task.definition.components {
                    ensure!(
                        self.component_load(c) < self.policy.wip_limit_per_component,
                        "work-in-progress limit reached for component '{c}'"
                    );
                }
                let conflicts = self.conflicts(task);
                ensure!(
                    conflicts.is_empty(),
                    "overlaps files of active tasks: {}",
                    conflicts.join(", ")
                );
                let expiry = self.lease(task, now)?;
                task.status = Claimed;
                task.claimant = Some(actor.into());
                task.renewals = 0;
                task.lease_expires = Some(expiry);
                task.votes.clear();
                task.approval = Value::Null;
                task.submission = Value::Null;
                task.attempts
                    .push(json!({"actor": actor, "from": time(now), "to": null, "outcome": null}));
                format!("claimed by @{actor} until {}", time(expiry))
            }
            "start" => {
                ensure!(status == Claimed, "task is {status}");
                task.status = InProgress;
                "work started".into()
            }
            "renew" => {
                ensure!(status.leased(), "task is {status}, nothing to renew");
                ensure!(
                    task.renewals < self.policy.max_renewals,
                    "maximum number of renewals reached; submit, release or ask a maintainer"
                );
                let expiry = self.lease(task, now)?;
                task.renewals += 1;
                task.lease_expires = Some(expiry);
                if status == Claimed {
                    task.status = InProgress;
                }
                format!("lease renewed until {}", time(expiry))
            }
            "release" => {
                ensure!(status.active(), "task is {status}, nothing to release");
                ensure!(
                    claimant == Some(actor) || self.maintainer(actor),
                    "only the claimant or a maintainer can release a task"
                );
                task.end_attempt(now, "released");
                task.status = Available;
                task.claimant = None;
                task.lease_expires = None;
                task.submission = Value::Null;
                task.votes.clear();
                task.approval = Value::Null;
                "released, task is available again".into()
            }
            "submit" => {
                ensure!(
                    status.leased() || status.waiting(),
                    "task is {status}, cannot submit"
                );
                let sub = &ev["submission"];
                let error = text(&sub["error"]);
                ensure!(error.is_empty(), "{error}");
                let sha = text(&sub["head_sha"]);
                ensure!(
                    sub["pr"].as_u64().is_some_and(|n| n > 0),
                    "submission is missing 'pr'"
                );
                ensure!(!sha.is_empty(), "submission is missing 'head_sha'");
                ensure!(
                    !text(&sub["author"]).is_empty(),
                    "submission is missing 'author'"
                );
                ensure!(
                    sub["author"] == actor,
                    "the pull request must be authored by the claimant"
                );
                ensure!(
                    task.submission["head_sha"] != sha,
                    "duplicate submission: this commit is already under validation"
                );
                let fp = text(&sub["patch_id"]);
                if !fp.is_empty() {
                    let previous = self
                        .patches
                        .entry(fp.into())
                        .or_insert_with(|| task.definition.id.clone());
                    ensure!(
                        *previous == task.definition.id,
                        "identical patch already submitted for {previous}"
                    );
                }
                task.submission = json!({"at": time(now)});
                for key in ["pr", "head_sha", "author", "patch_id", "violations"] {
                    if let Some(value) = sub.get(key) {
                        task.submission[key] = value.clone();
                    }
                }
                task.votes.clear();
                task.approval = Value::Null;
                task.lease_expires = None;
                task.status = Submitted;
                let violations = strings(&sub["violations"]);
                let note = if violations.is_empty() {
                    String::new()
                } else {
                    format!(
                        " — touches protected paths, maintainer review required: {}",
                        violations.join(", ")
                    )
                };
                format!(
                    "submission #{} @ {} recorded, waiting for independent validation{note}",
                    sub["pr"],
                    short_sha(sha)
                )
            }
            "vote" | "approve" => {
                let head = text(&task.submission["head_sha"]);
                let sha = text(&ev["sha"]).to_ascii_lowercase();
                let prefix = if kind == "vote" {
                    ensure!(status.review(), "task is {status}, nothing to validate");
                    ensure!(
                        task.submission["author"] != actor && claimant != Some(actor),
                        "authors cannot validate their own contribution"
                    );
                    let verdict = text(&ev["verdict"]);
                    ensure!(
                        matches!(verdict, "pass" | "fail"),
                        "verdict must be 'pass' or 'fail'"
                    );
                    ensure!(
                        sha.len() >= 7 && head.starts_with(&sha),
                        "vote must reference the submitted commit {}",
                        short_sha(head)
                    );
                    let evidence = text(&ev["evidence"]);
                    ensure!(
                        !evidence.is_empty(),
                        "a vote must include evidence (link to logs or a results report)"
                    );
                    task.votes.insert(actor.into(), json!({"verdict": verdict, "sha": head, "evidence": evidence, "at": time(now)}));
                    format!("{verdict} vote from @{actor} recorded")
                } else {
                    ensure!(self.maintainer(actor), "only maintainers can approve");
                    ensure!(status.waiting(), "task is {status}, nothing to approve");
                    ensure!(
                        sha.len() >= 7 && head.starts_with(&sha),
                        "approval must reference the submitted commit {}",
                        short_sha(head)
                    );
                    task.approval = json!({"by": actor, "sha": head, "at": time(now)});
                    "maintainer approval recorded".into()
                };
                format!("{prefix}; {}", self.evaluate(task, now)?)
            }
            "merged" | "pr_closed" | "pr_updated" => {
                let action = match kind {
                    "merged" => "merge",
                    "pr_closed" => "close",
                    _ => "update",
                };
                ensure!(
                    actor == SYSTEM,
                    "{action} events can only come from the coordinator"
                );
                ensure!(
                    !task.submission.is_null()
                        && task.submission["pr"] == ev["pr"]
                        && (kind == "merged" || status.review()),
                    "pull request is not the current submission"
                );
                match kind {
                    "merged" => {
                        let mut audit = vec![];
                        if status != ReadyToMerge {
                            audit.push(format!("merged while {status}"));
                        }
                        if ev["head_sha"] != task.submission["head_sha"] {
                            audit.push("merged commit differs from the submitted commit".into());
                        }
                        task.end_attempt(now, "merged");
                        task.status = Merged;
                        task.lease_expires = None;
                        task.submission["audit"] = json!(audit);
                        if audit.is_empty() {
                            "merged".into()
                        } else {
                            format!("merged — AUDIT: {}", audit.join("; "))
                        }
                    }
                    "pr_closed" => {
                        task.lease_expires = Some(self.lease(task, now)?);
                        task.status = InProgress;
                        task.submission = Value::Null;
                        task.votes.clear();
                        task.approval = Value::Null;
                        "pull request closed without merge; task returned to its claimant".into()
                    }
                    _ => {
                        task.submission["head_sha"] = ev["head_sha"].clone();
                        task.submission["patch_id"] = ev["patch_id"].clone();
                        task.submission["violations"] =
                            ev.get("violations").cloned().unwrap_or_else(|| json!([]));
                        task.votes.clear();
                        task.approval = Value::Null;
                        task.status = Submitted;
                        format!(
                            "new commit {} pushed, previous votes no longer apply",
                            short_sha(text(&ev["head_sha"]))
                        )
                    }
                }
            }
            "block" => {
                ensure!(
                    claimant == Some(actor) || self.maintainer(actor),
                    "only the claimant or a maintainer can block a task"
                );
                ensure!(!status.terminal(), "task is {status}");
                let reason = text(&ev["reason"]);
                ensure!(!reason.is_empty(), "a reason is required");
                task.end_attempt(now, "blocked");
                task.status = Blocked;
                task.claimant = None;
                task.lease_expires = None;
                task.block_reason = json!(reason);
                format!("task blocked: {reason}")
            }
            "unblock" | "reopen" | "reject" | "cancel" => {
                ensure!(self.maintainer(actor), "only maintainers can do this");
                let (next, outcome) = match kind {
                    "unblock" => (Available, "unblocked"),
                    "reopen" => (Available, "reopened"),
                    "reject" => (Rejected, "rejected"),
                    _ => (Cancelled, "cancelled"),
                };
                ensure!(
                    !status.terminal() || next == Available,
                    "task is already {status}"
                );
                ensure!(
                    next != Available || status.terminal() || status == Blocked,
                    "task is {status}, nothing to reopen"
                );
                task.end_attempt(now, outcome);
                task.status = next;
                task.claimant = None;
                task.lease_expires = None;
                task.block_reason = Value::Null;
                format!("task is now {next}")
            }
            _ => bail!("unrecognised command; see PROTOCOL.md for the exact syntax"),
        };
        Ok(msg)
    }

    fn apply(&mut self, ev: &Value) -> Result<()> {
        let id = ev["id"].as_str().context("missing event id")?;
        if !self.seen.insert(id.into()) {
            return Ok(());
        }
        self.advance(ev["time"].as_str().context("missing event time")?.parse()?);
        let now = self.clock.unwrap();
        let kind = ev["kind"].as_str().context("missing event kind")?;
        match kind {
            "policy" | "task" => {
                ensure!(
                    ev["actor"] == SYSTEM,
                    "configuration event must come from the coordinator"
                );
                if kind == "policy" {
                    self.policy = serde_json::from_value(ev["policy"].clone())?;
                } else {
                    let raw = ev["task"].clone();
                    let definition: Definition = serde_json::from_value(raw.clone())?;
                    ensure!(definition.risk != Risk::Never, "invalid task risk");
                    if let Some(task) = self.tasks.get_mut(&definition.id) {
                        task.raw = raw;
                        task.definition = definition;
                    } else {
                        self.tasks
                            .insert(definition.id.clone(), Task::new(raw, definition));
                    }
                }
                return Ok(());
            }
            "tick" => return Ok(()),
            _ => {}
        }
        let task_id = ev["task"].as_str().unwrap_or("None");
        let result = if let Some(mut task) = self.tasks.remove(task_id) {
            let result = self.transition(&mut task, ev, now);
            self.tasks.insert(task_id.into(), task);
            result
        } else if matches!(
            kind,
            "claim"
                | "start"
                | "renew"
                | "release"
                | "submit"
                | "vote"
                | "approve"
                | "merged"
                | "pr_closed"
                | "pr_updated"
                | "block"
                | "unblock"
                | "reopen"
                | "reject"
                | "cancel"
        ) {
            Err(anyhow::anyhow!("unknown task {task_id}"))
        } else {
            Err(anyhow::anyhow!(
                "unrecognised command; see PROTOCOL.md for the exact syntax"
            ))
        };
        let accepted = result.is_ok();
        let message = result.unwrap_or_else(|e| e.to_string());
        self.decisions.push(
            json!({"event": id, "task": ev["task"], "actor": ev["actor"], "kind": kind,
            "issue": ev["issue"], "accepted": accepted, "message": message}),
        );
        Ok(())
    }
}

pub fn fold(events: &[Value], until: Option<Clock>) -> Result<State> {
    let mut state = State::default();
    for event in events {
        state
            .apply(event)
            .with_context(|| format!("replaying event {}", event["id"]))?;
    }
    if let Some(now) = until {
        state.advance(now);
    }
    Ok(state)
}

pub fn text(value: &Value) -> &str {
    value.as_str().unwrap_or_default()
}
pub fn strings(value: &Value) -> Vec<&str> {
    value
        .as_array()
        .into_iter()
        .flatten()
        .filter_map(Value::as_str)
        .collect()
}
fn short_sha(sha: &str) -> String {
    sha.chars().take(12).collect()
}
