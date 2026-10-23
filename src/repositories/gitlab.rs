//! GitLab public metadata and nested-namespace README handling.
//!
//! [`fetch`] checks identity before secondary reads. README URLs are used only to
//! recover an inspected path; file bytes are fetched through the GitLab project API.

use super::client::{encode, path_valid};
use super::{
    Repository, RepositoryRef,
    client::{self, readme_base},
    web_url,
};
use crate::{
    error::{Error, Result},
    http,
};
use percent_encoding::percent_decode_str;
use reqwest::{Client, header::HeaderMap};
use serde::Deserialize;
use url::Url;
/// GitLab license fields used to choose a human-readable identifier.
#[derive(Deserialize)]
struct License {
    /// Preferred human-readable short license identifier.
    nickname: Option<String>,
    /// Fallback license key.
    key: Option<String>,
    /// Fallback full license name.
    name: Option<String>,
}
/// GitLab repository metadata required for public visibility and identity checks.
#[derive(Deserialize)]
struct Gitlab {
    /// Nonzero stable numeric project ID.
    id: u64,
    /// Observed nested namespace/project path checked against the request.
    path_with_namespace: String,
    /// Project display name.
    name: String,
    /// Must equal `public` before secondary reads.
    visibility: String,
    /// Optional untrusted project description.
    description: Option<String>,
    /// Optional blob URL used only to recover the inspected README path.
    readme_url: Option<String>,
    /// Branch prefix required to interpret the README blob path.
    default_branch: Option<String>,
    /// Optional project topic list, empty when absent.
    #[serde(default)]
    topics: Vec<String>,
    /// Optional public license metadata.
    license: Option<License>,
}
/// Read the optional README through the project API using its inspected file path.
///
/// Requires a matching GitLab blob URL and default branch; unsupported or absent
/// metadata becomes `None`. Invalid UTF-8 in content is replaced lossily.
///
/// # Errors
///
/// Propagates provider read failures and rejects invalid README paths as payload errors.
async fn gitlab_readme(
    client: &Client,
    root: &str,
    headers: &HeaderMap,
    reference: &RepositoryRef,
    metadata: &Gitlab,
) -> Result<Option<(String, Url)>> {
    let Some((readme_url, branch)) = metadata
        .readme_url
        .as_deref()
        .zip(metadata.default_branch.as_deref())
    else {
        return Ok(None);
    };
    let Some(url) = web_url(readme_url).filter(|u| {
        u.scheme() == "https" && u.host_str() == Some("gitlab.com") && u.port().is_none()
    }) else {
        return Ok(None);
    };
    let path = percent_decode_str(url.path())
        .decode_utf8()
        .map_err(|_| Error::Payload)?;
    let prefix = format!("/{}/-/blob/{branch}/", reference.full_name());
    let Some(file) = path.strip_prefix(&prefix).filter(|file| path_valid(file)) else {
        return Ok(None);
    };
    let bytes = http::get(
        client,
        &format!("{root}/repository/files/{}/raw?ref=HEAD", encode(file)),
        headers,
    )
    .await?;
    bytes
        .map(|bytes| {
            Ok((
                String::from_utf8_lossy(&bytes).into_owned(),
                readme_base(reference, file)?,
            ))
        })
        .transpose()
}

/// Check public GitLab identity before loading secondary repository resources.
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
    let root = format!(
        "https://gitlab.com/api/v4/projects/{}",
        encode(&requested.full_name())
    );
    let metadata: Gitlab = http::json(client, &format!("{root}?license=true"), headers)
        .await?
        .ok_or(Error::NotFound)?;
    if metadata.visibility != "public" {
        return Err(Error::NotFound);
    }
    if metadata.id == 0
        || !metadata
            .path_with_namespace
            .eq_ignore_ascii_case(&requested.full_name())
    {
        return Err(Error::Payload);
    }
    let reference = RepositoryRef::parse(&format!(
        "https://gitlab.com/{}",
        metadata.path_with_namespace
    ))?;
    let root = format!("https://gitlab.com/api/v4/projects/{}", metadata.id);
    let (readme, languages, release) = tokio::try_join!(
        gitlab_readme(client, &root, headers, &reference, &metadata),
        client::languages(client, &root, headers),
        client::release(client, &root, headers, &reference)
    )?;
    client::finish(
        Repository {
            reference,
            provider_id: metadata.id.to_string(),
            display_name: metadata.name,
            description: metadata.description,
            readme: None,
            languages,
            license: metadata
                .license
                .and_then(|v| v.nickname.or(v.key).or(v.name)),
            topics: metadata.topics,
            release,
            links: Vec::new(),
        },
        readme,
        None,
    )
}
