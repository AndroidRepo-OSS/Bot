//! GitHub metadata adapter with public visibility and requested-path checks.
//!
//! Only after these checks does [`fetch`] read README, language and release data
//! concurrently. README base64 failures become absent content rather than raw errors.

use super::{
    Repository, RepositoryRef,
    client::{self, readme_base},
    web_url,
};
use crate::{
    error::{Error, Result},
    http,
};
use base64::{Engine, engine::general_purpose::STANDARD};
use reqwest::{Client, header::HeaderMap};
use serde::Deserialize;
use url::Url;
/// GitHub license fields used to choose a human-readable identifier.
#[derive(Deserialize)]
struct License {
    /// Optional SPDX ID; `NOASSERTION` is discarded.
    spdx_id: Option<String>,
    /// Human-readable fallback when no usable SPDX ID exists.
    name: Option<String>,
}
/// GitHub repository metadata required for public visibility and identity checks.
#[derive(Deserialize)]
struct Github {
    /// Nonzero numeric repository identity.
    id: u64,
    /// Preferred stable GraphQL node ID when present.
    node_id: Option<String>,
    /// Observed owner/repository path checked against the request.
    full_name: String,
    /// Project display name.
    name: String,
    /// Private visibility flag; true forbids secondary evidence reads.
    private: bool,
    /// Must equal `public`, including when authenticated.
    visibility: String,
    /// Optional untrusted project description.
    description: Option<String>,
    /// Optional project website URL subject to syntax filtering.
    homepage: Option<String>,
    /// Optional project topic list, empty when absent.
    #[serde(default)]
    topics: Vec<String>,
    /// Optional public license metadata.
    license: Option<License>,
}
/// GitHub README JSON containing base64 content, encoding and file path.
#[derive(Deserialize)]
struct Readme {
    /// Base64-encoded README content.
    content: String,
    /// Encoding marker; only base64 is supported.
    encoding: String,
    /// Inspected file path used for relative-link resolution.
    path: String,
}
/// Decode the optional base64 README and retain its inspected file URL.
///
/// Missing resources, unsupported encodings and invalid base64 become `None`;
/// invalid UTF-8 is replaced lossily.
///
/// # Errors
///
/// Propagates provider read failures and rejects invalid README paths as payload errors.
async fn github_readme(
    client: &Client,
    root: &str,
    headers: &HeaderMap,
    reference: &RepositoryRef,
) -> Result<Option<(String, Url)>> {
    let Some(payload): Option<Readme> =
        http::json(client, &format!("{root}/readme"), headers).await?
    else {
        return Ok(None);
    };
    if !payload.encoding.eq_ignore_ascii_case("base64") {
        return Ok(None);
    }
    let compact: String = payload
        .content
        .chars()
        .filter(|c| !c.is_whitespace())
        .collect();
    let Ok(content) = STANDARD.decode(compact) else {
        return Ok(None);
    };
    Ok(Some((
        String::from_utf8_lossy(&content).into_owned(),
        readme_base(reference, &payload.path)?,
    )))
}

/// Check public GitHub identity before loading secondary repository resources.
///
/// The returned path must match the requested repository; redirects are not followed.
///
/// # Errors
///
/// Returns [`Error::NotFound`] for absent/private evidence, [`Error::Payload`] for
/// inconsistent identity, or sanitized provider/JSON errors for resource failures.
pub(super) async fn fetch(
    client: &Client,
    requested: &RepositoryRef,
    headers: &HeaderMap,
) -> Result<Repository> {
    let root = format!("https://api.github.com/repos/{}", requested.full_name());
    let metadata: Github = http::json(client, &root, headers)
        .await?
        .ok_or(Error::NotFound)?;
    if metadata.private || metadata.visibility != "public" {
        return Err(Error::NotFound);
    }
    if metadata.id == 0
        || !metadata
            .full_name
            .eq_ignore_ascii_case(&requested.full_name())
    {
        return Err(Error::Payload);
    }
    let reference = RepositoryRef::parse(&format!("https://github.com/{}", metadata.full_name))?;
    let (readme, languages, release) = tokio::try_join!(
        github_readme(client, &root, headers, &reference),
        client::languages(client, &root, headers),
        client::release(client, &root, headers, &reference)
    )?;
    let homepage = metadata.homepage.and_then(|s| web_url(&s));
    client::finish(
        Repository {
            reference,
            provider_id: metadata.node_id.unwrap_or_else(|| metadata.id.to_string()),
            display_name: metadata.name,
            description: metadata.description,
            readme: None,
            languages,
            license: metadata
                .license
                .and_then(|v| v.spdx_id.filter(|s| s != "NOASSERTION").or(v.name)),
            topics: metadata.topics,
            release,
            links: Vec::new(),
        },
        readme,
        homepage,
    )
}
