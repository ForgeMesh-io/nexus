use crate::coordinator::Inbox;
use anyhow::{Context, Result, bail, ensure};
use regex::Regex;
use serde_json::{Value, json};
use std::{
    collections::HashSet,
    sync::LazyLock,
    thread,
    time::{Duration, SystemTime, UNIX_EPOCH},
};
use ureq::http::{HeaderMap, Uri};

pub struct GitHub {
    agent: ureq::Agent,
    api: Uri,
    api_base: String,
    repo: String,
    token: String,
}

pub fn valid_repo(repo: &str) -> bool {
    let valid = |s: &str| {
        !s.is_empty()
            && !matches!(s, "." | "..")
            && s.bytes()
                .all(|b| b.is_ascii_alphanumeric() || b"-_.".contains(&b))
    };
    repo.split_once('/')
        .is_some_and(|(owner, name)| valid(owner) && valid(name))
}

impl GitHub {
    pub fn new(api: &str, repo: &str, token: String) -> Result<Self> {
        ensure!(valid_repo(repo), "repository must be OWNER/REPO");
        let api_base = api.trim_end_matches('/').to_owned();
        let uri: Uri = api_base.parse().context("invalid GitHub API base URL")?;
        ensure!(
            uri.authority().is_some_and(|a| !a.as_str().contains('@')) && uri.query().is_none(),
            "invalid GitHub API base URL"
        );
        let local = uri.host() == Some("127.0.0.1") && token.is_empty();
        ensure!(
            uri.scheme_str() == Some("https") || (local && uri.scheme_str() == Some("http")),
            "GitHub API requires HTTPS"
        );
        let agent = ureq::Agent::config_builder()
            .http_status_as_error(false)
            .max_redirects(0)
            .timeout_global(Some(Duration::from_secs(60)))
            .build()
            .into();
        Ok(Self {
            agent,
            api: uri,
            api_base,
            repo: repo.into(),
            token,
        })
    }

    fn request(
        &self,
        url: &str,
        accept: &str,
        body: Option<&Value>,
    ) -> Result<Option<(String, HeaderMap)>> {
        let target: Uri = url.parse().context("invalid GitHub API link")?;
        ensure!(
            target.scheme() == self.api.scheme() && target.authority() == self.api.authority(),
            "GitHub API link has a different origin"
        );
        let auth = format!("Bearer {}", self.token);
        for attempt in 0..6 {
            let response = if let Some(body) = body {
                let mut request = self
                    .agent
                    .post(url)
                    .header("Accept", accept)
                    .header("X-GitHub-Api-Version", "2022-11-28")
                    .header("User-Agent", "forgemesh-coordinator");
                if !self.token.is_empty() {
                    request = request.header("Authorization", &auth);
                }
                request.send_json(body)
            } else {
                let mut request = self
                    .agent
                    .get(url)
                    .header("Accept", accept)
                    .header("X-GitHub-Api-Version", "2022-11-28")
                    .header("User-Agent", "forgemesh-coordinator");
                if !self.token.is_empty() {
                    request = request.header("Authorization", &auth);
                }
                request.call()
            };
            let mut response =
                response.map_err(|_| anyhow::anyhow!("could not reach GitHub API"))?;
            let status = response.status();
            if status.is_success() {
                let headers = response.headers().clone();
                let raw = response
                    .body_mut()
                    .with_config()
                    .limit(32 * 1024 * 1024)
                    .read_to_string()
                    .context("reading GitHub API response")?;
                return Ok(Some((raw, headers)));
            }
            if status == 404 {
                return Ok(None);
            }
            // Do not retry an ambiguous POST after a server error: the reply may already exist.
            if attempt < 5
                && (matches!(status.as_u16(), 403 | 429)
                    || (status.is_server_error() && body.is_none()))
            {
                let header = |key| response.headers().get(key).and_then(|v| v.to_str().ok());
                let min = if status.is_server_error() {
                    1 << attempt
                } else {
                    5 << attempt
                };
                let now = SystemTime::now()
                    .duration_since(UNIX_EPOCH)
                    .unwrap_or_default()
                    .as_secs();
                let rate_reset = header("x-ratelimit-reset")
                    .and_then(|s| s.parse::<u64>().ok())
                    .filter(|_| header("x-ratelimit-remaining") == Some("0"))
                    .map(|t| t.saturating_sub(now));
                let wait = header("retry-after")
                    .and_then(|s| s.parse::<u64>().ok())
                    .or(rate_reset)
                    .unwrap_or(0);
                thread::sleep(Duration::from_secs(wait.clamp(min, 300)));
                continue;
            }
            bail!("GitHub API returned HTTP {status}");
        }
        bail!("GitHub API retries exhausted");
    }

    fn url(&self, path: &str) -> String {
        format!("{}/repos/{}{path}", self.api_base, self.repo)
    }

    fn pages(&self, path: &str) -> Result<Vec<Value>> {
        static NEXT: LazyLock<Regex> =
            LazyLock::new(|| Regex::new(r#"<([^>]+)>;\s*rel="next""#).unwrap());
        let separator = if path.contains('?') { '&' } else { '?' };
        let mut url = self.url(&format!("{path}{separator}per_page=100"));
        let mut seen = HashSet::new();
        let mut values = vec![];
        loop {
            ensure!(
                seen.len() < 1_000 && seen.insert(url.clone()),
                "GitHub pagination did not terminate"
            );
            let (body, headers) = self
                .request(&url, "application/vnd.github+json", None)?
                .context("GitHub API page not found")?;
            values.extend(
                serde_json::from_str::<Vec<Value>>(&body).context("invalid GitHub API page")?,
            );
            let Some(next) = headers
                .get("link")
                .and_then(|v| v.to_str().ok())
                .and_then(|s| NEXT.captures(s))
            else {
                return Ok(values);
            };
            url = next[1].to_owned();
        }
    }
}

impl Inbox for GitHub {
    fn comments_since(&self, since: Option<&str>) -> Result<Vec<Value>> {
        let mut path = "/issues/comments?sort=created&direction=asc".to_owned();
        if let Some(since) = since {
            path.push_str(&format!("&since={since}"));
        }
        self.pages(&path)
    }

    fn reply(&self, issue: u64, body: &str) -> Result<()> {
        self.request(
            &self.url(&format!("/issues/{issue}/comments")),
            "application/vnd.github+json",
            Some(&json!({"body": body})),
        )?
        .context("GitHub issue not found")?;
        Ok(())
    }

    fn pull(&self, number: u64) -> Result<Option<Value>> {
        self.request(
            &self.url(&format!("/pulls/{number}")),
            "application/vnd.github+json",
            None,
        )?
        .map(|(s, _)| serde_json::from_str(&s).context("invalid GitHub pull request"))
        .transpose()
    }

    fn files(&self, number: u64) -> Result<Vec<String>> {
        self.pages(&format!("/pulls/{number}/files"))?
            .iter()
            .try_fold(vec![], |mut paths, f| {
                paths.push(
                    f["filename"]
                        .as_str()
                        .context("missing PR file name")?
                        .to_owned(),
                );
                if let Some(previous) = f["previous_filename"].as_str() {
                    paths.push(previous.into());
                }
                Ok(paths)
            })
    }

    fn diff(&self, number: u64) -> Result<String> {
        Ok(self
            .request(
                &self.url(&format!("/pulls/{number}")),
                "application/vnd.github.diff",
                None,
            )?
            .context("GitHub pull request diff not found")?
            .0)
    }
}
