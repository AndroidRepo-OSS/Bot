//! Load configuration without mutating the process environment after Tokio starts.
use crate::error::{Error, Result};
use std::{collections::HashMap, env};

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

pub struct Settings(HashMap<String, String>);
impl Settings {
    pub fn load() -> Result<Self> {
        let mut values = HashMap::new();
        match dotenvy::from_path_iter(".env") {
            Ok(entries) => {
                for entry in entries {
                    let (key, value) = entry.map_err(|_| Error::Config("invalid .env file"))?;
                    values.insert(key, value);
                }
            }
            Err(dotenvy::Error::Io(error)) if error.kind() == std::io::ErrorKind::NotFound => {}
            Err(_) => return Err(Error::Config("cannot read .env file")),
        }
        values.extend(env::vars().filter(|(key, _)| key.starts_with("AR_")));
        Ok(Self(values))
    }
    pub fn optional(&self, key: &str) -> Option<String> {
        self.0.get(key).filter(|v| !v.trim().is_empty()).cloned()
    }
    fn required(&self, key: &'static str) -> Result<String> {
        self.optional(key).ok_or(Error::Config(key))
    }
    pub fn database_url(&self) -> Result<String> {
        let value = self.required("AR_DATABASE_URL")?;
        crate::db::options(&value)?;
        Ok(value)
    }
    pub fn config(&self) -> Result<Config> {
        let integer = |key| {
            self.required(key)?
                .parse::<i64>()
                .map_err(|_| Error::Config(key))
        };
        let nonzero = |key| {
            integer(key).and_then(|v| {
                if v != 0 {
                    Ok(v)
                } else {
                    Err(Error::Config(key))
                }
            })
        };
        let topic = |key| {
            integer(key).and_then(|v| {
                i32::try_from(v)
                    .ok()
                    .filter(|v| *v > 0)
                    .ok_or(Error::Config(key))
            })
        };
        let log_level = self
            .optional("AR_LOG_LEVEL")
            .unwrap_or_else(|| "INFO".into());
        let log_level = match log_level.to_uppercase().as_str() {
            "CRITICAL" | "ERROR" => "error",
            "WARNING" | "WARN" => "warn",
            "INFO" => "info",
            "DEBUG" => "debug",
            _ => return Err(Error::Config("AR_LOG_LEVEL")),
        }
        .to_owned();
        Ok(Config {
            bot_token: self.required("AR_BOT_TOKEN")?,
            staff_chat: nonzero("AR_STAFF_CHAT_ID")?,
            post_topic: topic("AR_POST_TOPIC_ID")?,
            log_topic: topic("AR_LOG_TOPIC_ID")?,
            channel: nonzero("AR_CHANNEL_ID")?,
            zen_key: self.required("AR_OPENCODE_ZEN_API_KEY")?,
            zen_model: self
                .optional("AR_OPENCODE_ZEN_MODEL")
                .unwrap_or_else(|| "mimo-v2.6-flash-free".into()),
            github_token: self.optional("AR_GITHUB_TOKEN"),
            gitlab_token: self.optional("AR_GITLAB_TOKEN"),
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
