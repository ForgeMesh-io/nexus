use forgemesh::core::{State, Task};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{
    cmp::Reverse,
    collections::{BTreeMap, HashSet},
};

pub fn recommend(state: &State, actor: &str, capabilities: &HashSet<String>, salt: &str) -> Value {
    let matches = |task: &Task| {
        task.definition
            .hardware
            .iter()
            .all(|tag| capabilities.contains(tag))
    };
    let queue = state.tasks.values().filter(|t| t.status.waiting()).count();
    let policy = &state.policy;
    let pressure = &policy.validation_pressure;
    let share = if queue <= pressure.low_queue {
        pressure.dev_share_low
    } else if queue >= pressure.high_queue {
        pressure.dev_share_high
    } else {
        pressure.dev_share_mid
    };
    let digest = Sha256::digest(format!("{actor}|{salt}"));
    let bucket =
        f64::from(u32::from_be_bytes(digest[..4].try_into().unwrap())) / f64::from(u32::MAX);
    let mut validate = state
        .tasks
        .values()
        .filter(|t| {
            t.status.waiting()
                && !t.submission.is_null()
                && t.claimant.as_deref() != Some(actor)
                && t.submission["author"] != actor
                && !t.votes.contains_key(actor)
                && matches(t)
        })
        .collect::<Vec<_>>();
    validate.sort_by_key(|t| {
        (
            t.definition.priority,
            t.submission["at"].as_str().unwrap_or(""),
            &t.definition.id,
        )
    });
    let mut develop = state
        .tasks
        .values()
        .filter(|t| {
            state.display_status(t).claimable()
                && state.conflicts(t).is_empty()
                && matches(t)
                && t.definition
                    .components
                    .iter()
                    .all(|c| state.component_load(c) < policy.wip_limit_per_component)
        })
        .collect::<Vec<_>>();
    let review_first = queue > 0 && bucket >= share;
    develop.sort_by_key(|t| {
        let d = &t.definition;
        let review = matches!(
            d.kind.as_str(),
            "reviewer" | "validator" | "challenger" | "integrator" | "benchmarker" | "security"
        );
        let unblocks = state
            .tasks
            .values()
            .filter(|other| other.definition.depends_on.contains(&d.id))
            .count();
        (
            !review_first || !review,
            d.priority,
            Reverse(unblocks),
            Reverse(d.hardware.len()),
            &d.id,
        )
    });
    // Back-pressure must not send a participant to an empty queue when they can still contribute.
    let mode = if !validate.is_empty() && (review_first || develop.is_empty() || policy.paused) {
        "validate"
    } else {
        "develop"
    };
    let validate = &validate[..validate.len().min(5)];
    let develop = &develop[..develop.len().min(5)];
    let ids = |tasks: &[&Task]| {
        tasks
            .iter()
            .map(|t| t.definition.id.clone())
            .collect::<Vec<_>>()
    };
    let tasks: BTreeMap<_, _> = validate
        .iter()
        .chain(develop)
        .map(|t| {
            let mut spec = t.raw.clone();
            spec["status"] = json!(state.display_status(t));
            (&t.definition.id, spec)
        })
        .collect();
    json!({"mode": mode, "validation_queue": queue, "in_review": state.tasks.values().filter(|t| t.status.review()).count(),
        "validate": ids(validate), "claim": ids(develop), "paused": policy.paused, "tasks": tasks})
}
