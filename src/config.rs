//! Typed TOML configuration; credentials never appear in diagnostics.
use crate::error::{Error, Result};
use std::path::Path;

// No Debug: these values include credentials.
pub struct Config {
    pub bot_token: String,
    pub staff_chat: i64,
    pub post_topic: i32,
    pub log_topic: i32,
    pub channel: i64,
    pub zen_key: String,
    pub zen_model: String,
    pub github_token: Option<String>,
    pub gitlab_token: Option<String>,
    pub database_url: String,
    pub log_level: String,
}

// No Debug: file settings also contain credentials.
#[derive(Default, serde::Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct Settings {
    bot_token: Option<String>,
    staff_chat_id: Option<i64>,
    post_topic_id: Option<i32>,
    log_topic_id: Option<i32>,
    channel_id: Option<i64>,
    opencode_zen_api_key: Option<String>,
    opencode_zen_model: Option<String>,
    github_token: Option<String>,
    gitlab_token: Option<String>,
    database_url: Option<String>,
    log_level: Option<String>,
}

fn optional(value: &Option<String>) -> Option<String> {
    value.as_ref().filter(|v| !v.trim().is_empty()).cloned()
}
fn required(value: &Option<String>, key: &'static str) -> Result<String> {
    optional(value).ok_or(Error::Config(key))
}

impl Settings {
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

    pub fn provider_token(&self, provider: crate::repositories::Provider) -> Option<String> {
        match provider {
            crate::repositories::Provider::Github => optional(&self.github_token),
            crate::repositories::Provider::Gitlab => optional(&self.gitlab_token),
        }
    }

    pub fn database_url(&self) -> Result<String> {
        let value = required(&self.database_url, "database_url")?;
        crate::db::options(&value)?;
        Ok(value)
    }

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
    pub fn provider_token(&self, provider: crate::repositories::Provider) -> Option<&str> {
        match provider {
            crate::repositories::Provider::Github => self.github_token.as_deref(),
            crate::repositories::Provider::Gitlab => self.gitlab_token.as_deref(),
        }
    }
}
