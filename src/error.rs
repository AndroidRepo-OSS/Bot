//! Sanitized application errors and conversions at external boundaries.
//!
//! [`enum@Error`] retains only safe categories or static messages, never raw external
//! error payloads, credentials or response bodies. [`Result`] is shared by modules.

use thiserror::Error;

/// Application result using the sanitized [`enum@Error`] categories.
pub type Result<T> = std::result::Result<T, Error>;

/// Safe application failures suitable for staff responses and structured logs.
///
/// Conversions discard raw external errors. Static configuration and validation
/// messages must never contain credentials, private text or response bodies.
#[derive(Debug, Error)]
pub enum Error {
    /// Invalid configuration, identified by a safe static key/message.
    #[error("Invalid configuration: {0}")]
    Config(&'static str),
    /// Validation or workflow refusal expressed as safe static text.
    #[error("{0}")]
    Invalid(&'static str),
    /// Missing or nonpublic repository evidence.
    #[error("Repository not found. Check that the URL is public and spelled correctly.")]
    NotFound,
    /// Provider request rejected due to rate limiting.
    #[error("Provider rate limit reached. Try again later.")]
    RateLimit,
    /// External operation exceeded its allowed deadline.
    #[error("The external service timed out. Try again shortly.")]
    Timeout,
    /// Sanitized external transport/status/client failure.
    #[error("The external service is temporarily unavailable.")]
    External,
    /// Malformed, incompatible or excessive external data.
    #[error("The external service returned invalid or excessive data.")]
    Payload,
    /// Sanitized SQLite/query/migration failure.
    #[error("Publication storage is temporarily unavailable.")]
    Database,
    /// Structured generation failed the output contract.
    #[error("Could not produce a valid grounded draft. Try again later.")]
    Generation,
    /// Image decoding, layout or PNG production failed.
    #[error("Could not render the banner.")]
    Image,
    /// Sanitized Telegram API failure.
    #[error("Telegram request failed. Check permissions and try again.")]
    Telegram,
    /// Sanitized local file read/write failure.
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
