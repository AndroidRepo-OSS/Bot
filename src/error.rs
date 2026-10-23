//! Deliberately safe errors: never retain response bodies, credentials, or URLs.
use thiserror::Error;

pub type Result<T> = std::result::Result<T, Error>;

#[derive(Debug, Error)]
pub enum Error {
    #[error("Invalid configuration: {0}")]
    Config(&'static str),
    #[error("{0}")]
    Invalid(&'static str),
    #[error("Repository not found. Check that the URL is public and spelled correctly.")]
    NotFound,
    #[error("Provider rate limit reached. Try again later.")]
    RateLimit,
    #[error("The external service timed out. Try again shortly.")]
    Timeout,
    #[error("The external service is temporarily unavailable.")]
    External,
    #[error("The external service returned invalid or excessive data.")]
    Payload,
    #[error("Publication storage is temporarily unavailable.")]
    Database,
    #[error("Could not produce a valid grounded draft. Try again later.")]
    Generation,
    #[error("Could not render the banner.")]
    Image,
    #[error("Telegram request failed. Check permissions and try again.")]
    Telegram,
    #[error("Could not read or write the requested local file.")]
    Io,
}
impl From<reqwest::Error> for Error {
    fn from(error: reqwest::Error) -> Self {
        if error.is_timeout() {
            Self::Timeout
        } else {
            Self::External
        }
    }
}
impl From<sqlx::Error> for Error {
    fn from(_: sqlx::Error) -> Self {
        Self::Database
    }
}
impl From<serde_json::Error> for Error {
    fn from(_: serde_json::Error) -> Self {
        Self::Payload
    }
}
impl From<teloxide::RequestError> for Error {
    fn from(_: teloxide::RequestError) -> Self {
        Self::Telegram
    }
}
impl From<std::io::Error> for Error {
    fn from(_: std::io::Error) -> Self {
        Self::Io
    }
}
