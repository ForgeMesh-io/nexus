mod capabilities;
mod sandbox;
mod scheduler;

use anyhow::{Context, Result, ensure};
use chrono::Utc;
use clap::{Args, Parser, Subcommand};
use forgemesh::{
    config, coordinator, core,
    github::{GitHub, valid_repo},
    journal,
};
use serde_json::{Value, json};
use std::{
    collections::HashSet, ffi::OsString, fs, path::PathBuf, process::ExitCode, time::Duration,
};

#[derive(Parser)]
#[command(version, about = "GitHub-native swarm coordination")]
struct Cli {
    #[command(subcommand)]
    command: Action,
}

#[derive(Subcommand)]
enum Action {
    /// Report coarse local capability tags.
    Capabilities,
    /// Show the verified project's optional resource questions. Does not probe for resources.
    Resources {
        #[arg(default_value = ".")]
        root: PathBuf,
    },
    /// Validate the local swarm configuration.
    CheckConfig {
        #[arg(default_value = ".")]
        root: PathBuf,
    },
    /// Process the GitHub inbox and publish the swarm state.
    Coordinate {
        #[arg(long)]
        repo: String,
        #[arg(long)]
        state_dir: PathBuf,
        #[arg(long, default_value = ".")]
        config_root: PathBuf,
        #[arg(long)]
        full_scan: bool,
    },
    /// Run a command in a disposable, no-network Docker workspace.
    Sandbox {
        #[arg(long)]
        image: String,
        #[arg(long)]
        source: PathBuf,
        #[command(flatten)]
        limits: sandbox::Limits,
        #[arg(last = true, required = true, num_args = 1..)]
        command: Vec<OsString>,
    },
    /// Test a committed tree in the sandbox and print an unsigned attestation.
    Attest {
        #[arg(long)]
        task_file: PathBuf,
        #[arg(long)]
        source: PathBuf,
        #[arg(long)]
        image: Option<String>,
        #[arg(long)]
        gpu: bool,
    },
    /// Show current task state.
    Status {
        #[command(flatten)]
        source: Source,
        #[arg(long)]
        task: Option<String>,
    },
    /// Recommend work using public state and locally confirmed capabilities.
    Next {
        #[command(flatten)]
        source: Source,
        #[arg(long)]
        actor: String,
        #[arg(long = "capability")]
        capabilities: Vec<String>,
        /// Optional resource identifier confirmed by the human. Never pass a file or device path.
        #[arg(long = "resource")]
        resources: Vec<String>,
    },
}

#[derive(Args)]
#[group(required = true, multiple = false)]
struct Source {
    #[arg(long)]
    repo: Option<String>,
    #[arg(long)]
    journal: Option<PathBuf>,
}

fn read_journal(source: &Source) -> Result<Vec<Value>> {
    if let Some(path) = &source.journal {
        return journal::parse(
            &fs::read_to_string(path).with_context(|| format!("reading {}", path.display()))?,
        );
    }
    let repo = source
        .repo
        .as_deref()
        .context("--repo or --journal is required")?;
    ensure!(valid_repo(repo), "repository must be OWNER/REPO");
    let agent: ureq::Agent = ureq::Agent::config_builder()
        .timeout_global(Some(Duration::from_secs(60)))
        .build()
        .into();
    let mut response = match agent
        .get(format!(
            "https://raw.githubusercontent.com/{repo}/forgemesh-state/journal.jsonl"
        ))
        .call()
    {
        Ok(response) => response,
        Err(ureq::Error::StatusCode(404)) => return Ok(vec![]),
        Err(e) => return Err(e).context("fetching swarm journal"),
    };
    // shortcut: full replay is bounded to 32 MiB over HTTP; add checkpoints before journals reach this size.
    journal::parse(
        &response
            .body_mut()
            .with_config()
            .limit(32 * 1024 * 1024)
            .read_to_string()?,
    )
}

fn run() -> Result<ExitCode> {
    let now = Utc::now();
    let value = match Cli::parse().command {
        Action::Capabilities => capabilities::detect(),
        Action::Resources { root } => json!(config::resources(&root)?),
        Action::CheckConfig { root } => {
            let (policy, tasks) = config::load(&root)?;
            println!(
                "OK: swarm '{}', {} task(s)",
                core::text(&policy["swarm"]),
                tasks.len()
            );
            return Ok(ExitCode::SUCCESS);
        }
        Action::Status { source, task } => {
            let state = core::fold(&read_journal(&source)?, Some(now))?.snapshot();
            match task {
                Some(id) => state["tasks"]
                    .get(&id)
                    .cloned()
                    .unwrap_or_else(|| json!({"error": "unknown task"})),
                None => state,
            }
        }
        Action::Coordinate {
            repo,
            state_dir,
            config_root,
            full_scan,
        } => {
            let (policy, tasks) = config::load(&config_root)?;
            let api =
                std::env::var("GITHUB_API_URL").unwrap_or_else(|_| "https://api.github.com".into());
            let token = std::env::var("GITHUB_TOKEN").context("GITHUB_TOKEN is required")?;
            ensure!(!token.is_empty(), "GITHUB_TOKEN is required");
            coordinator::run(
                &GitHub::new(&api, &repo, token)?,
                &state_dir,
                &policy,
                &tasks,
                full_scan,
                now,
            )?
        }
        Action::Sandbox {
            image,
            source,
            limits,
            command,
        } => {
            let code = sandbox::execute(&image, &source, &command, &limits)?;
            return Ok(ExitCode::from(u8::try_from(code).unwrap_or(1)));
        }
        Action::Attest {
            task_file,
            source,
            image,
            gpu,
        } => {
            let report = sandbox::attest(&task_file, &source, image.as_deref(), gpu)?;
            println!("{}", serde_json::to_string_pretty(&report)?);
            return Ok(if report["predicate"]["passed"] == true {
                ExitCode::SUCCESS
            } else {
                ExitCode::FAILURE
            });
        }
        Action::Next {
            source,
            actor,
            capabilities,
            resources,
        } => {
            let detected;
            let mut tags: HashSet<String> = if capabilities.is_empty() {
                detected = capabilities::detect();
                core::strings(&detected["tags"])
                    .into_iter()
                    .map(str::to_owned)
                    .collect()
            } else {
                capabilities
                    .into_iter()
                    .filter(|c| !c.starts_with("resource:"))
                    .collect()
            };
            for id in resources {
                ensure!(
                    config::valid_resource_id(&id),
                    "invalid resource identifier; pass an ID, not a path"
                );
                tags.insert(format!("resource:{id}"));
            }
            let state = core::fold(&read_journal(&source)?, Some(now))?;
            scheduler::recommend(&state, &actor, &tags, &now.format("%Y-%m-%d").to_string())
        }
    };
    println!("{}", serde_json::to_string_pretty(&value)?);
    Ok(ExitCode::SUCCESS)
}

fn main() -> ExitCode {
    match run() {
        Ok(code) => code,
        Err(e) => {
            eprintln!("{e:#}");
            ExitCode::FAILURE
        }
    }
}
