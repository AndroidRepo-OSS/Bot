//! Public repository evidence independent of Telegram presentation.
//!
//! [`RepositoryRef`] admits clean supported roots. [`fetch`] verifies public
//! visibility before secondary reads even when authenticated. [`Repository`] keeps
//! stable provider identity, untrusted metadata and snapshot-scoped [`Link`] IDs.
//! Generation selects these IDs; it never supplies the final destination URLs.

mod client;
mod github;
mod gitlab;
mod links;
mod reference;

pub use reference::{Provider, RepositoryRef, web_url};
use serde::Serialize;
use url::Url;

/// Evidence-based destination category used by generation link selection.
///
/// Classification identifies eligible sources; it does not fetch or audit the
/// contents of a destination. See [`Self::is_download_candidate`].
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum LinkKind {
    /// Mandatory repository root, inserted separately from optional selections.
    Repository,
    /// Provider release page eligible for the Download button.
    Release,
    /// Recognized Android app-store destination eligible for download.
    AppStore,
    /// Recognized Android package repository eligible for download.
    PackageRepository,
    /// Documentation identified from visible labels or path components.
    Documentation,
    /// Project homepage from provider metadata.
    Website,
    /// Issue tracker or support/help destination.
    Support,
    /// Donation/sponsorship destination excluded from optional post links.
    Donation,
    /// Inspected destination without a more specific category.
    Other,
}
impl LinkKind {
    /// Whether this category may supply the draft Download button.
    ///
    /// Only releases, app stores and package repositories qualify.
    pub fn is_download_candidate(self) -> bool {
        matches!(
            self,
            Self::Release | Self::AppStore | Self::PackageRepository
        )
    }
    /// Whether generation may select this as an optional caption link.
    ///
    /// Repository links are inserted separately; donation links are excluded.
    pub fn is_optional_destination(self) -> bool {
        !matches!(self, Self::Repository | Self::Donation)
    }
}
/// An inspected destination with an ID scoped to one [`Repository`] snapshot.
#[derive(Clone, Debug, Serialize)]
pub struct Link {
    /// Exact selection key scoped to this evidence snapshot.
    pub id: String,
    /// Observed label normalized for evidence, not yet model-output validation.
    pub label: String,
    /// Parsed destination derived from provider metadata or README evidence.
    pub url: Url,
    /// Eligibility category for download and optional-link selection.
    pub kind: LinkKind,
}
/// Latest release metadata observed through a public provider API.
#[derive(Clone, Debug, Serialize)]
pub struct Release {
    /// Release display name, falling back to its tag.
    pub name: String,
    /// Nonblank provider release tag.
    pub tag: String,
    /// Optional untrusted release notes.
    pub description: Option<String>,
    /// Provider release destination derived from the inspected tag.
    pub url: Url,
}
/// Normalized public evidence shared by generation, rendering and registration.
///
/// Provider identity is stable across renames; [`Self::reference`] records the
/// observed path. README text and other provider fields remain untrusted evidence.
/// Selected link IDs must be resolved against this same snapshot with [`Self::link`].
#[derive(Clone, Debug, Serialize)]
pub struct Repository {
    /// Provider-confirmed repository path.
    pub reference: RepositoryRef,
    /// Stable provider repository ID used for persistence across renames.
    pub provider_id: String,
    /// Nonblank project display name from public metadata.
    pub display_name: String,
    /// Optional untrusted project description.
    pub description: Option<String>,
    /// Optional nonblank README content, decoded lossily if needed.
    pub readme: Option<String>,
    /// Language names sorted by descending provider weight.
    pub languages: Vec<String>,
    /// Optional SPDX identifier or human-readable license fallback.
    pub license: Option<String>,
    /// Provider-supplied untrusted project topics.
    pub topics: Vec<String>,
    /// Optional latest release observed through the provider API.
    pub release: Option<Release>,
    /// Inspected destinations and snapshot-scoped selection IDs.
    pub links: Vec<Link>,
}
impl Repository {
    /// Look up an exact evidence ID, returning `None` when it was not inspected.
    pub fn link(&self, id: &str) -> Option<&Link> {
        self.links.iter().find(|link| link.id == id)
    }
    /// Whether any inspected link is eligible for the Download button.
    pub fn has_download(&self) -> bool {
        self.links
            .iter()
            .any(|link| link.kind.is_download_candidate())
    }
}

/// Load and normalize a public GitHub or GitLab repository.
///
/// Checks visibility even with `token`, then loads README, languages and release
/// metadata concurrently. Credentials are sent only to the selected provider API.
/// Use [`crate::http::client`] to preserve redirects and response limits.
///
/// # Errors
///
/// Returns [`crate::error::Error::NotFound`] for missing or nonpublic repositories,
/// sanitized provider failures for unsuccessful reads, and payload/configuration
/// errors for invalid metadata or credentials.
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
