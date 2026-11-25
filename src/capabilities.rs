use regex::Regex;
use serde_json::{Value, json};
use std::{collections::BTreeSet, env, fs, process::Command, sync::LazyLock};

fn has_tool(name: &str) -> bool {
    env::var_os("PATH")
        .iter()
        .flat_map(env::split_paths)
        .any(|dir| {
            let path = dir.join(format!("{name}{}", env::consts::EXE_SUFFIX));
            let Ok(metadata) = path.metadata() else {
                return false;
            };
            #[cfg(unix)]
            {
                use std::os::unix::fs::PermissionsExt;
                metadata.is_file() && metadata.permissions().mode() & 0o111 != 0
            }
            #[cfg(not(unix))]
            metadata.is_file()
        })
}

fn probe(tool: &str, args: &[&str]) -> String {
    // shortcut: bounded Linux probes only, add platform-specific probes when needed.
    if !cfg!(target_os = "linux") || !has_tool(tool) || !has_tool("timeout") {
        return String::new();
    }
    Command::new("timeout")
        .args(["-k", "2", "20", tool])
        .args(args)
        .output()
        .map(|output| String::from_utf8_lossy(&output.stdout).into_owned())
        .unwrap_or_default()
}

pub fn detect() -> Value {
    let arch = match env::consts::ARCH {
        "x86" => "i686",
        "aarch64" if cfg!(target_os = "macos") => "arm64",
        a => a,
    };
    let os = if cfg!(target_os = "macos") {
        "darwin"
    } else {
        env::consts::OS
    };
    let mut tags = BTreeSet::from([format!("os:{os}"), format!("arch:{arch}")]);
    for tool in [
        "git",
        "gh",
        "docker",
        "podman",
        "python3",
        "cmake",
        "ninja",
        "clang",
        "gcc",
        "cargo",
        "vulkaninfo",
    ] {
        if has_tool(tool) {
            tags.insert(format!("tool:{tool}"));
        }
    }
    let mut gpus = Vec::new();
    static VULKAN: LazyLock<Regex> = LazyLock::new(|| {
        Regex::new(r"(?s)deviceName\s*=\s*([^\n]+)\n.*?driverID\s*=\s*(\S+)").unwrap()
    });
    static POLARIS: LazyLock<Regex> =
        LazyLock::new(|| Regex::new(r"ellesmere|polaris|rx ?(4[6-8]0|5[5-9]0)").unwrap());
    for captures in VULKAN.captures_iter(&probe("vulkaninfo", &["--summary"])) {
        let name = captures[1].trim();
        let driver = &captures[2];
        if name.to_ascii_lowercase().contains("llvmpipe")
            || driver.to_ascii_lowercase().contains("lavapipe")
        {
            continue;
        }
        tags.insert("gpu:vulkan".into());
        gpus.push((name.to_owned(), Some(driver.to_owned())));
    }
    if gpus.is_empty() {
        for line in probe("lspci", &[]).lines().filter(|l| {
            ["VGA", "3D controller", "Display controller"]
                .iter()
                .any(|s| l.contains(s))
        }) {
            gpus.push((
                line.split_once(": ")
                    .map_or(line, |(_, name)| name)
                    .trim()
                    .into(),
                None,
            ));
        }
    }
    for (name, driver) in &gpus {
        let name = name.to_ascii_lowercase();
        let mut add = |tag: &str| {
            tags.insert(tag.to_owned());
        };
        if ["amd", "radeon", "ati"].iter().any(|s| name.contains(s)) {
            add("gpu:amd");
            if POLARIS.is_match(&name) {
                add("gpu:gfx803");
            }
        } else if name.contains("nvidia") || name.contains("geforce") {
            add("gpu:nvidia");
        } else if name.contains("intel") {
            add("gpu:intel");
        }
        if driver
            .as_ref()
            .is_some_and(|d| d.to_ascii_uppercase().ends_with("RADV"))
            || name.contains("radv")
        {
            add("driver:radv");
        }
    }
    let cpus = std::thread::available_parallelism().map_or(1, usize::from);
    for n in [4, 8, 16] {
        if cpus >= n {
            tags.insert(format!("cpu:{n}c"));
        }
    }
    let ram = fs::read_to_string("/proc/meminfo")
        .ok()
        .and_then(|s| {
            s.lines().find_map(|l| {
                l.strip_prefix("MemTotal:")?
                    .split_whitespace()
                    .next()?
                    .parse::<u64>()
                    .ok()
            })
        })
        .unwrap_or(0)
        / (1024 * 1024);
    for n in [8, 16, 32, 64] {
        if ram >= n {
            tags.insert(format!("ram:{n}g"));
        }
    }
    let gpus: Vec<_> = gpus
        .iter()
        .map(|(name, driver)| json!({"name": name, "driver": driver}))
        .collect();
    json!({"tags": tags, "gpus": gpus, "cpus": cpus, "ram_gb": ram})
}
