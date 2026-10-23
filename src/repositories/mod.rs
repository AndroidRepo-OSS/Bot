//! Public repository evidence; destination URLs are resolved here, never by AI.
mod client;
mod github;
mod gitlab;
mod links;
mod reference;

pub use reference::{Provider, RepositoryRef, web_url};
use serde::Serialize;
use url::Url;

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum LinkKind {
    Repository,
    Release,
    AppStore,
    PackageRepository,
    Documentation,
    Website,
    Support,
    Donation,
    Other,
}
impl LinkKind {
    pub fn download(self) -> bool {
        matches!(
            self,
            Self::Release | Self::AppStore | Self::PackageRepository
        )
    }
    pub fn optional(self) -> bool {
        !matches!(self, Self::Repository | Self::Donation)
    }
}
#[derive(Clone, Debug, Serialize)]
pub struct Link {
    pub id: String,
    pub label: String,
    pub url: Url,
    pub kind: LinkKind,
}
#[derive(Clone, Debug, Serialize)]
pub struct Release {
    pub name: String,
    pub tag: String,
    pub description: Option<String>,
    pub url: Url,
}
#[derive(Clone, Debug, Serialize)]
pub struct Repository {
    pub reference: RepositoryRef,
    pub provider_id: String,
    pub display_name: String,
    pub description: Option<String>,
    pub readme: Option<String>,
    pub languages: Vec<String>,
    pub license: Option<String>,
    pub topics: Vec<String>,
    pub release: Option<Release>,
    pub links: Vec<Link>,
}
impl Repository {
    pub fn link(&self, id: &str) -> Option<&Link> {
        self.links.iter().find(|link| link.id == id)
    }
    pub fn has_download(&self) -> bool {
        self.links.iter().any(|link| link.kind.download())
    }
}

/// Load one public repository and normalize its provider-specific responses.
pub async fn fetch(
    client: &reqwest::Client,
    requested: &RepositoryRef,
    token: Option<&str>,
) -> crate::error::Result<Repository> {
    let headers = client::headers(requested.provider, token)?;
    match requested.provider {
        Provider::Github => github::fetch(client, requested, &headers).await,
        Provider::Gitlab => gitlab::fetch(client, requested, &headers).await,
    }
}
