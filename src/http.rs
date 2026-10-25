//! Shared connection pooling and byte-bounded external reads.
//!
//! [`client`] disables redirects and has no default credentials. [`get`] retries
//! read-only metadata requests; mutation requests such as Telegram channel copies
//! must not reuse its retry policy. [`bounded`] enforces limits while streaming.

use crate::error::{Error, Result};
use bytes::{Bytes, BytesMut};
use reqwest::{Client, Response, header::HeaderMap};
use serde::de::DeserializeOwned;
use std::time::Duration;

/// Maximum provider/API metadata body size in bytes (4 MiB).
pub const METADATA_LIMIT: usize = 4 * 1024 * 1024;

/// Build the shared HTTP connection pool with redirects and internal retries disabled.
///
/// Uses a five-second connection timeout and a 30-second request timeout. Credentials
/// are attached by callers to individual requests, never as pool-wide defaults.
///
/// # Errors
///
/// Returns [`Error::External`] if the HTTP client cannot be initialized.
pub fn client() -> Result<Client> {
    Ok(Client::builder()
        .user_agent("androidrepo-bot/0.1")
        .redirect(reqwest::redirect::Policy::none())
        .retry(reqwest::retry::never())
        .connect_timeout(Duration::from_secs(5))
        .timeout(Duration::from_secs(30))
        .pool_idle_timeout(Duration::from_secs(90))
        .pool_max_idle_per_host(8)
        .build()?)
}

/// Consume a response body without exceeding `limit` bytes.
///
/// Checks both the declared content length and streamed chunks. This function does
/// not validate the HTTP status or content type; callers must check them first.
///
/// # Errors
///
/// Returns [`Error::Payload`] when the body exceeds the limit, or a sanitized
/// transport error when reading fails. A partially read body is discarded.
pub async fn bounded(mut response: Response, limit: usize) -> Result<Bytes> {
    if response
        .content_length()
        .is_some_and(|length| length > limit as u64)
    {
        return Err(Error::Payload);
    }
    let mut body = BytesMut::new();
    while let Some(chunk) = response.chunk().await? {
        if chunk.len() > limit.saturating_sub(body.len()) {
            return Err(Error::Payload);
        }
        body.extend_from_slice(&chunk);
    }
    Ok(body.freeze())
}

/// Read bounded metadata with at most three GET attempts.
///
/// Returns `None` for HTTP 404. Retries selected connection failures, timeouts,
/// HTTP 408 and server errors with bounded backoff; body streaming is not retried.
/// Only use provider-scoped headers with the intended origin. Redirects must be
/// disabled on the supplied client, as in [`client`].
///
/// # Errors
///
/// Returns [`Error::RateLimit`] for rate limiting, [`Error::Payload`] for an oversized
/// body, or sanitized timeout/transport/status errors for other failures.
pub async fn get(client: &Client, url: &str, headers: &HeaderMap) -> Result<Option<Bytes>> {
    for attempt in 0..3 {
        let response = client.get(url).headers(headers.clone()).send().await;
        let response = match response {
            Ok(response) => response,
            Err(error)
                if attempt < 2 && (error.is_timeout() || error.is_connect() || error.is_body()) =>
            {
                tokio::time::sleep(Duration::from_millis(250 << attempt)).await;
                continue;
            }
            Err(error) => return Err(error.into()),
        };
        let status = response.status();
        if status.as_u16() == 404 {
            return Ok(None);
        }
        if status.as_u16() == 429
            || (status.as_u16() == 403
                && response
                    .headers()
                    .get("x-ratelimit-remaining")
                    .is_some_and(|v| v == "0"))
        {
            return Err(Error::RateLimit);
        }
        if (status.is_server_error() || status.as_u16() == 408) && attempt < 2 {
            let delay = response
                .headers()
                .get("retry-after")
                .and_then(|v| v.to_str().ok())
                .and_then(|v| v.parse::<u64>().ok())
                .map(|s| Duration::from_secs(s.min(5)))
                .unwrap_or(Duration::from_millis(250 << attempt));
            tokio::time::sleep(delay).await;
            continue;
        }
        if !status.is_success() {
            return Err(Error::External);
        }
        return bounded(response, METADATA_LIMIT).await.map(Some);
    }
    Err(Error::External)
}

/// Deserialize optional JSON metadata retrieved through [`get`].
///
/// A missing resource remains `None`; successful responses must match `T`.
///
/// # Errors
///
/// Propagates [`get`] failures and returns [`Error::Payload`] for malformed JSON
/// or a response incompatible with `T`.
pub async fn json<T: DeserializeOwned>(
    client: &Client,
    url: &str,
    headers: &HeaderMap,
) -> Result<Option<T>> {
    get(client, url, headers)
        .await?
        .map(|bytes| serde_json::from_slice(&bytes).map_err(Into::into))
        .transpose()
}
