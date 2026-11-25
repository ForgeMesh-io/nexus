use anyhow::{Context, Result, ensure};
use regex::Regex;
use serde_json::Value;
use std::{
    collections::{BTreeMap, BTreeSet},
    fs,
    io::ErrorKind,
    path::Path,
    sync::LazyLock,
};

use crate::core::{strings, text};

static RESOURCE_ID: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"\A[a-z0-9][a-z0-9_-]{0,39}\z").unwrap());

pub fn valid_resource_id(id: &str) -> bool {
    RESOURCE_ID.is_match(id)
}

pub fn resources(root: &Path) -> Result<BTreeMap<String, String>> {
    let path = root.join(".forgemesh/resources.json");
    let raw = match fs::read(&path) {
        Ok(raw) => raw,
        Err(e) if e.kind() == ErrorKind::NotFound => return Ok(BTreeMap::new()),
        Err(e) => return Err(e).with_context(|| format!("reading {}", path.display())),
    };
    let entries: BTreeMap<String, String> =
        serde_json::from_slice(&raw).with_context(|| format!("parsing {}", path.display()))?;
    for (id, question) in &entries {
        ensure!(valid_resource_id(id), "invalid resource identifier {id:?}");
        ensure!(
            question.ends_with('?')
                && question.chars().count() <= 200
                && !question.chars().any(char::is_control),
            "resource {id} needs a plain, single-line question (max 200 characters)"
        );
    }
    Ok(entries)
}

pub fn task(path: &Path) -> Result<Value> {
    validated(
        path,
        &validator(include_str!("../forgemesh/schemas/task.schema.json"))?,
    )
}

pub fn load(root: &Path) -> Result<(Value, Vec<Value>)> {
    let dir = root.join(".forgemesh");
    let policy_validator = validator(include_str!("../forgemesh/schemas/policy.schema.json"))?;
    let task_validator = validator(include_str!("../forgemesh/schemas/task.schema.json"))?;
    let policy = validated(&dir.join("policy.json"), &policy_validator)?;
    let resources = resources(root)?;
    let tasks_dir = dir.join("tasks");
    let mut paths = match fs::read_dir(&tasks_dir) {
        Ok(items) => items
            .map(|item| item.map(|i| i.path()))
            .collect::<std::io::Result<Vec<_>>>()?,
        Err(e) if e.kind() == ErrorKind::NotFound => vec![],
        Err(e) => return Err(e).with_context(|| format!("reading {}", tasks_dir.display())),
    };
    paths.sort();
    let mut tasks = vec![];
    let mut fallback = false;
    for path in paths
        .iter()
        .filter(|p| p.extension().is_some_and(|e| e == "json"))
    {
        let task = validated(path, &task_validator)?;
        let id = text(&task["id"]);
        ensure!(
            path.file_stem().and_then(|s| s.to_str()) == Some(id),
            "{}: file name must be <id>.json",
            path.display()
        );
        ensure!(
            task["swarm"] == policy["swarm"],
            "{id}: swarm does not match policy"
        );
        let requirements = strings(&task["hardware"]);
        for resource in requirements
            .iter()
            .filter_map(|r| r.strip_prefix("resource:"))
        {
            ensure!(
                resources.contains_key(resource),
                "{id}: undeclared resource {resource}"
            );
        }
        fallback |= requirements.is_empty()
            && strings(&task["depends_on"]).is_empty()
            && task["execution"] == "none";
        tasks.push(task);
    }
    if !resources.is_empty() {
        ensure!(
            fallback,
            "swarm with private resources needs at least one independent task without private resources or code execution"
        );
    }
    let deps: BTreeMap<_, _> = tasks
        .iter()
        .map(|t| (text(&t["id"]), strings(&t["depends_on"])))
        .collect();
    let mut done = BTreeSet::new();
    let mut visiting = BTreeSet::new();
    for id in deps.keys() {
        visit(id, &deps, &mut done, &mut visiting)?;
    }
    Ok((policy, tasks))
}

fn visit<'a>(
    id: &'a str,
    deps: &BTreeMap<&'a str, Vec<&'a str>>,
    done: &mut BTreeSet<&'a str>,
    visiting: &mut BTreeSet<&'a str>,
) -> Result<()> {
    if done.contains(id) {
        return Ok(());
    }
    ensure!(visiting.insert(id), "dependency cycle through {id}");
    for dep in &deps[id] {
        ensure!(deps.contains_key(dep), "{id}: unknown dependency {dep}");
        visit(dep, deps, done, visiting)?;
    }
    visiting.remove(id);
    done.insert(id);
    Ok(())
}

fn validator(schema: &str) -> Result<jsonschema::Validator> {
    Ok(jsonschema::draft202012::new(&serde_json::from_str(
        schema,
    )?)?)
}

fn validated(path: &Path, validator: &jsonschema::Validator) -> Result<Value> {
    let value = serde_json::from_slice(
        &fs::read(path).with_context(|| format!("reading {}", path.display()))?,
    )
    .with_context(|| format!("parsing {}", path.display()))?;
    if let Err(error) = validator.validate(&value) {
        anyhow::bail!("{}{}: {error}", path.display(), error.instance_path());
    }
    Ok(value)
}
