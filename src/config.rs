//! Typed TOML configuration with command-specific validation.
//!
//! [`FileSettings`] holds optional input; [`Config`] is ready for polling. Neither
//! implements `Debug`, and parsing failures discard source-bearing diagnostics.
//! All settings come from TOML; process environment variables are not consulted.

use crate::error::{Error, Result};
use std::path::Path;

/// Validated polling configuration built by [`FileSettings::config`].
///
/// Contains credentials and deliberately has no `Debug` implementation. Provider
/// tokens are optional; Telegram, model and database settings are required.
// No Debug: these values include credentials.
pub struct Config {
    /// Telegram bot credential; never include it in logs.
    pub bot_token: String,
    /// Nonzero staff chat ID allowed to access protected actions.
    pub staff_chat: i64,
    /// Positive topic ID admitting draft and reconciliation actions.
    pub post_topic: i32,
    /// Positive topic ID for best-effort audit delivery.
    pub log_topic: i32,
    /// Nonzero target channel ID for publication.
    pub channel: i64,
    /// OpenCode API credential; never include it in logs.
    pub zen_key: String,
    /// Chat Completions model identifier supporting tool calls.
    pub zen_model: String,
    /// Optional GitHub API credential scoped to the GitHub origin.
    pub github_token: Option<String>,
    /// Optional GitLab API credential scoped to the GitLab origin.
    pub gitlab_token: Option<String>,
    /// Persistent file-backed SQLite connection URL.
    pub database_url: String,
    /// Normalized application tracing level; dependency events remain disabled.
    pub log_level: String,
}

/// Optional TOML fields before command-specific validation.
///
/// Unknown fields and invalid types are rejected. Missing values are allowed until
/// a command requests [`Self::config`] or [`Self::database_url`]. No environment
/// variables are read, and credentials deliberately have no `Debug` representation.
// No Debug: file settings also contain credentials.
#[derive(Default, serde::Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct FileSettings {
    /// Optional input: telegram bot credential; never include it in logs.
    bot_token: Option<String>,
    /// Optional input: nonzero staff chat ID allowed to access protected actions.
    staff_chat_id: Option<i64>,
    /// Optional input: positive topic ID admitting draft and reconciliation actions.
    post_topic_id: Option<i32>,
    /// Optional input: positive topic ID for best-effort audit delivery.
    log_topic_id: Option<i32>,
    /// Optional input: nonzero target channel ID for publication.
    channel_id: Option<i64>,
    /// Optional input: openCode API credential; never include it in logs.
    opencode_zen_api_key: Option<String>,
    /// Optional input: chat Completions model identifier supporting tool calls.
    opencode_zen_model: Option<String>,
    /// Optional input: optional GitHub API credential scoped to the GitHub origin.
    github_token: Option<String>,
    /// Optional input: optional GitLab API credential scoped to the GitLab origin.
    gitlab_token: Option<String>,
    /// Optional input: persistent file-backed SQLite connection URL.
    database_url: Option<String>,
    /// Optional input: normalized application tracing level; dependency events remain disabled.
    log_level: Option<String>,
}

/// Clone a nonblank setting, preserving its original nonblank contents.
fn optional(value: &Option<String>) -> Option<String> {
    value.as_ref().filter(|v| !v.trim().is_empty()).cloned()
}
/// Read a required nonblank setting.
///
/// # Errors
///
/// Returns [`Error::Config`] with the static key when the value is absent or blank.
fn required(value: &Option<String>, key: &'static str) -> Result<String> {
    optional(value).ok_or(Error::Config(key))
}

impl FileSettings {
    /// Read TOML settings without exposing source text in diagnostics.
    ///
    /// `allow_missing` accepts only a nonexistent file, returning default empty settings;
    /// permission, encoding and parse failures remain errors.
    ///
    /// # Errors
    ///
    /// Returns [`Error::Config`] for unreadable files, malformed TOML, unknown keys or
    /// invalid field types. Parser diagnostics are discarded because they may contain secrets.
    pub async fn load(path: &Path, allow_missing: bool) -> Result<Self> {
        let source = match tokio::fs::read_to_string(path).await {
            Ok(source) => source,
            Err(error) if allow_missing && error.kind() == std::io::ErrorKind::NotFound => {
                return Ok(Self::default());
            }
            Err(_) => return Err(Error::Config("cannot read configuration file")),
        };
        // Parser errors can include source text containing secrets.
        toml::from_str(&source)
            .map_err(|_| Error::Config("invalid TOML configuration or field type"))
    }

    /// Return the nonblank credential for the selected provider, if configured.
    pub fn provider_token(&self, provider: crate::repositories::Provider) -> Option<String> {
        match provider {
            crate::repositories::Provider::Github => optional(&self.github_token),
            crate::repositories::Provider::Gitlab => optional(&self.gitlab_token),
        }
    }

    /// Validate and return the persistent SQLite URL using [`crate::db::options`].
    ///
    /// # Errors
    ///
    /// Returns [`Error::Config`] for an absent, blank or unsupported database URL.
    /// This validates options without opening the database.
    pub fn database_url(&self) -> Result<String> {
        let value = required(&self.database_url, "database_url")?;
        crate::db::options(&value)?;
        Ok(value)
    }

    /// Validate all settings needed to poll Telegram.
    ///
    /// Requires nonzero chat/channel IDs and positive topic IDs. Defaults the model and
    /// normalizes the supported log levels; blank optional provider tokens become `None`.
    ///
    /// # Errors
    ///
    /// Returns [`Error::Config`] for missing required settings, invalid IDs, unsupported
    /// log levels or a database URL rejected by [`crate::db::options`].
    pub fn config(&self) -> Result<Config> {
        let nonzero = |value: Option<i64>, key| value.filter(|v| *v != 0).ok_or(Error::Config(key));
        let topic = |value: Option<i32>, key| value.filter(|v| *v > 0).ok_or(Error::Config(key));
        let log_level = optional(&self.log_level).unwrap_or_else(|| "INFO".into());
        let log_level = match log_level.to_uppercase().as_str() {
            "CRITICAL" | "ERROR" => "error",
            "WARNING" | "WARN" => "warn",
            "INFO" => "info",
            "DEBUG" => "debug",
            _ => return Err(Error::Config("log_level")),
        }
        .to_owned();
        Ok(Config {
            bot_token: required(&self.bot_token, "bot_token")?,
            staff_chat: nonzero(self.staff_chat_id, "staff_chat_id")?,
            post_topic: topic(self.post_topic_id, "post_topic_id")?,
            log_topic: topic(self.log_topic_id, "log_topic_id")?,
            channel: nonzero(self.channel_id, "channel_id")?,
            zen_key: required(&self.opencode_zen_api_key, "opencode_zen_api_key")?,
            zen_model: optional(&self.opencode_zen_model)
                .unwrap_or_else(|| "mimo-v2.6-flash-free".into()),
            github_token: optional(&self.github_token),
            gitlab_token: optional(&self.gitlab_token),
            database_url: self.database_url()?,
            log_level,
        })
    }
}

impl Config {
    /// Return the nonblank credential for the selected provider, if configured.
    pub fn provider_token(&self, provider: crate::repositories::Provider) -> Option<&str> {
        match provider {
            crate::repositories::Provider::Github => self.github_token.as_deref(),
            crate::repositories::Provider::Gitlab => self.gitlab_token.as_deref(),
        }
    }
}
