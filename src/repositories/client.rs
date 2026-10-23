//! Shared provider policy and normalized evidence assembly.
//!
//! Sensitive headers stay scoped to provider API origins. Secondary metadata uses
//! bounded reads; [`finish`] builds inert README links after identity validation.

use super::{Provider, Release, Repository, RepositoryRef, links, web_url};
use crate::{
    error::{Error, Result},
    http,
};
use percent_encoding::{NON_ALPHANUMERIC, utf8_percent_encode};
use reqwest::{
    Client,
    header::{ACCEPT, AUTHORIZATION, HeaderMap, HeaderValue},
};
use serde::Deserialize;
use std::collections::HashMap;
use url::Url;
/// Shared subset of GitHub/GitLab release JSON; descriptions use provider-specific keys.
#[derive(Deserialize)]
struct ReleasePayload {
    /// Optional release display name.
    name: Option<String>,
    /// Provider release tag required to build the destination.
    tag_name: String,
    /// GitHub release notes.
    body: Option<String>,
    /// GitLab release notes.
    description: Option<String>,
}

/// Percent-encode an untrusted value as one API path component.
pub(super) fn encode(value: &str) -> String {
    utf8_percent_encode(value, NON_ALPHANUMERIC).to_string()
}
/// Reject empty README paths, unsafe characters and empty/dot path components.
pub(super) fn path_valid(value: &str) -> bool {
    !value.is_empty()
        && !value
            .chars()
            .any(|c| c.is_control() || c.is_whitespace() || c == '\\')
        && !value.split('/').any(|part| matches!(part, "" | "." | ".."))
}
/// Build a provider web blob URL for resolving relative README links.
///
/// Uses the inspected file path and `HEAD`; it does not fetch that web URL.
///
/// # Errors
///
/// Returns [`Error::Payload`] for invalid file paths or an unrepresentable URL.
pub(super) fn readme_base(reference: &RepositoryRef, path: &str) -> Result<Url> {
    if !path_valid(path) {
        return Err(Error::Payload);
    }
    let path = path.split('/').map(encode).collect::<Vec<_>>().join("/");
    Url::parse(&format!(
        "{}/{}blob/HEAD/{path}",
        reference.url(),
        if reference.provider == Provider::Gitlab {
            "-/"
        } else {
            ""
        }
    ))
    .map_err(|_| Error::Payload)
}
/// Construct provider-specific API headers with a sensitive optional credential.
///
/// The caller must keep these headers on the selected provider origin.
///
/// # Errors
///
/// Returns [`Error::Config`] if the token cannot be represented as an HTTP header.
pub(super) fn headers(provider: Provider, token: Option<&str>) -> Result<HeaderMap> {
    let mut headers = HeaderMap::new();
    if provider == Provider::Github {
        headers.insert(
            ACCEPT,
            HeaderValue::from_static("application/vnd.github+json"),
        );
        headers.insert(
            "x-github-api-version",
            HeaderValue::from_static("2026-03-10"),
        );
    }
    if let Some(token) = token {
        let value = if provider == Provider::Github {
            format!("Bearer {token}")
        } else {
            token.into()
        };
        let mut value = HeaderValue::from_str(&value)
            .map_err(|_| Error::Config("invalid provider credential"))?;
        value.set_sensitive(true);
        headers.insert(
            if provider == Provider::Github {
                AUTHORIZATION
            } else {
                reqwest::header::HeaderName::from_static("private-token")
            },
            value,
        );
    }
    Ok(headers)
}
/// Read language weights and sort names by descending weight, then alphabetically.
///
/// A missing language resource becomes an empty list.
///
/// # Errors
///
/// Propagates bounded HTTP/JSON errors; returns [`Error::Payload`] for negative
/// or nonfinite language weights.
pub(super) async fn languages(
    client: &Client,
    root: &str,
    headers: &HeaderMap,
) -> Result<Vec<String>> {
    let values: HashMap<String, f64> = http::json(client, &format!("{root}/languages"), headers)
        .await?
        .unwrap_or_default();
    if values.values().any(|v| !v.is_finite() || *v < 0.0) {
        return Err(Error::Payload);
    }
    let mut values: Vec<_> = values.into_iter().collect();
    values.sort_by(|a, b| b.1.total_cmp(&a.1).then(a.0.cmp(&b.0)));
    Ok(values.into_iter().map(|(key, _)| key).collect())
}
/// Read the latest release and derive its destination from the inspected tag.
///
/// GitLab uses a sorted one-item list because its latest-release permalink redirects.
/// A missing release resource or empty list returns `None`.
///
/// # Errors
///
/// Propagates provider read failures and returns [`Error::Payload`] for a blank tag
/// or invalid derived destination.
pub(super) async fn release(
    client: &Client,
    root: &str,
    headers: &HeaderMap,
    reference: &RepositoryRef,
) -> Result<Option<Release>> {
    let payload: Option<ReleasePayload> = if reference.provider == Provider::Github {
        http::json(client, &format!("{root}/releases/latest"), headers).await?
    } else {
        // The permalink endpoint returns a redirect. The sorted list gives the
        // same release directly without forwarding credentials to a redirect.
        let releases: Option<Vec<ReleasePayload>> = http::json(
            client,
            &format!("{root}/releases?order_by=released_at&sort=desc&per_page=1"),
            headers,
        )
        .await?;
        releases.and_then(|items| items.into_iter().next())
    };
    let Some(payload) = payload else {
        return Ok(None);
    };
    if payload.tag_name.trim().is_empty() {
        return Err(Error::Payload);
    }
    let suffix = if reference.provider == Provider::Github {
        "releases/tag"
    } else {
        "-/releases"
    };
    let url = web_url(&format!(
        "{}/{suffix}/{}",
        reference.url(),
        encode(&payload.tag_name)
    ))
    .ok_or(Error::Payload)?;
    Ok(Some(Release {
        name: payload
            .name
            .filter(|v| !v.trim().is_empty())
            .unwrap_or_else(|| payload.tag_name.clone()),
        tag: payload.tag_name,
        description: payload.body.or(payload.description),
        url,
    }))
}

/// Validate repository identity and assemble links from the observed evidence.
///
/// Normalizes a blank README to `None` and resolves its links with the inspected
/// README file URL; destinations are never fetched here.
///
/// # Errors
///
/// Returns [`Error::Payload`] for empty/oversized provider IDs or display names.
pub(super) fn finish(
    mut repository: Repository,
    readme: Option<(String, Url)>,
    homepage: Option<Url>,
) -> Result<Repository> {
    if repository.provider_id.is_empty()
        || repository.provider_id.len() > 128
        || repository.display_name.trim().is_empty()
        || repository.display_name.chars().count() > 255
    {
        return Err(Error::Payload);
    }
    let (readme, base) = readme
        .map(|(text, url)| (Some(text).filter(|s| !s.trim().is_empty()), Some(url)))
        .unwrap_or_default();
    repository.links = links::build(
        web_url(&repository.reference.url()).ok_or(Error::Payload)?,
        repository.release.as_ref().map(|r| &r.url),
        homepage,
        readme.as_deref(),
        base.as_ref(),
    );
    repository.readme = readme;
    Ok(repository)
}
