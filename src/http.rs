//! Shared connection pool and bounded reads. Credentials are attached per request.
use crate::error::{Error, Result};
use bytes::{Bytes, BytesMut};
use reqwest::{Client, Response, header::HeaderMap};
use serde::de::DeserializeOwned;
use std::time::Duration;

pub const METADATA_LIMIT: usize = 4 * 1024 * 1024;

pub fn client() -> Result<Client> {
    Ok(Client::builder()
        .user_agent("androidrepo-bot/0.1")
        .redirect(reqwest::redirect::Policy::none())
        .connect_timeout(Duration::from_secs(5))
        .timeout(Duration::from_secs(30))
        .pool_idle_timeout(Duration::from_secs(90))
        .pool_max_idle_per_host(8)
        .build()?)
}

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
