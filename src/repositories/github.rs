//! GitHub public repository metadata and base64 README handling.
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
#[derive(Deserialize)]
struct License {
    spdx_id: Option<String>,
    name: Option<String>,
}
#[derive(Deserialize)]
struct Github {
    id: u64,
    node_id: Option<String>,
    full_name: String,
    name: String,
    private: bool,
    visibility: String,
    description: Option<String>,
    homepage: Option<String>,
    #[serde(default)]
    topics: Vec<String>,
    license: Option<License>,
}
#[derive(Deserialize)]
struct Readme {
    content: String,
    encoding: String,
    path: String,
}
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
