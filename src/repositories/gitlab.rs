//! GitLab nested namespaces, public visibility and branch-aware README paths.
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
#[derive(Deserialize)]
struct License {
    nickname: Option<String>,
    key: Option<String>,
    name: Option<String>,
}
#[derive(Deserialize)]
struct Gitlab {
    id: u64,
    path_with_namespace: String,
    name: String,
    visibility: String,
    description: Option<String>,
    readme_url: Option<String>,
    default_branch: Option<String>,
    #[serde(default)]
    topics: Vec<String>,
    license: Option<License>,
}
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
