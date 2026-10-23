//! Strict repository-root parsing and general evidence URL syntax checks.
//!
//! [`RepositoryRef::parse`] accepts only supported HTTPS roots; [`web_url`] is a
//! broader HTTP(S) syntax filter for destinations, not an outbound-fetch allowlist.

use crate::error::{Error, Result};
use serde::Serialize;
use url::Url;

/// Supported public hosted repository service; self-hosted instances are excluded.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "lowercase")]
pub enum Provider {
    /// The public `github.com` service.
    Github,
    /// The public `gitlab.com` service, including nested group namespaces.
    Gitlab,
}
impl Provider {
    /// Return the lowercase provider key used in persistence.
    pub fn name(self) -> &'static str {
        match self {
            Self::Github => "github",
            Self::Gitlab => "gitlab",
        }
    }
    /// Return the public web hostname used to construct repository URLs.
    pub fn host(self) -> &'static str {
        match self {
            Self::Github => "github.com",
            Self::Gitlab => "gitlab.com",
        }
    }
}
/// Provider and repository-root path, normally constructed by [`Self::parse`].
///
/// GitHub has one namespace component; GitLab permits nested groups. Fields are
/// not intrinsically validated when constructing this value directly.
#[derive(Clone, Debug, Serialize)]
pub struct RepositoryRef {
    /// Public host service for this path.
    pub provider: Provider,
    /// Owner or nested GitLab group path, without the repository name.
    pub namespace: String,
    /// Repository path component without a trailing `.git` suffix.
    pub name: String,
}
impl RepositoryRef {
    /// Parse a clean HTTPS repository-root URL for GitHub or GitLab.
    ///
    /// Trims surrounding whitespace and accepts a trailing slash or `.git` suffix.
    /// Rejects credentials, explicit ports, queries, fragments, encoded paths, dot
    /// segments and provider subresources. Nested GitLab namespaces are supported.
    /// For example, `https://gitlab.com/group/subgroup/project.git` has namespace
    /// `group/subgroup` and name `project`.
    ///
    /// # Errors
    ///
    /// Returns [`Error::Invalid`] for unsupported URL forms or paths, and
    /// [`Error::Payload`] for oversized namespace/name components.
    pub fn parse(value: &str) -> Result<Self> {
        let value = value.trim();
        let invalid = Error::Invalid(
            "Use an HTTPS GitHub or GitLab repository-root URL without credentials, ports, query strings, or fragments.",
        );
        let url = web_url(value).ok_or(invalid)?;
        // Check raw authority/path: URL parsers erase explicit default ports and dot segments.
        let authority = value
            .split_once("://")
            .map(|(_, rest)| rest.split('/').next().unwrap_or(rest))
            .unwrap_or("");
        let raw_path = value
            .split_once("://")
            .and_then(|(_, rest)| rest.split_once('/'))
            .map(|(_, path)| path)
            .unwrap_or("");
        if value.len() > 2048
            || url.scheme() != "https"
            || authority.contains(':')
            || url.query().is_some()
            || url.fragment().is_some()
            || raw_path.contains('%')
            || raw_path.contains("//")
        {
            return Err(Error::Invalid(
                "Only clean HTTPS repository roots are supported.",
            ));
        }
        let provider = match url.host_str() {
            Some("github.com") => Provider::Github,
            Some("gitlab.com") => Provider::Gitlab,
            _ => {
                return Err(Error::Invalid(
                    "Only github.com and gitlab.com are supported.",
                ));
            }
        };
        let path = raw_path
            .trim_end_matches('/')
            .strip_suffix(".git")
            .unwrap_or(raw_path.trim_end_matches('/'));
        let parts: Vec<_> = path.split('/').collect();
        if parts.len() < 2
            || (provider == Provider::Github && parts.len() != 2)
            || parts.iter().any(|part| {
                part.is_empty()
                    || matches!(*part, "." | "..")
                    || !part
                        .bytes()
                        .all(|c| c.is_ascii_alphanumeric() || b"_.-".contains(&c))
            })
            || (provider == Provider::Gitlab && parts.contains(&"-"))
        {
            return Err(Error::Invalid("The URL must point to a repository root."));
        }
        let (name, namespace) = parts.split_last().ok_or(Error::Payload)?;
        let namespace = namespace.join("/");
        if namespace.len() > 512 || name.len() > 255 {
            return Err(Error::Payload);
        }
        Ok(Self {
            provider,
            namespace,
            name: (*name).into(),
        })
    }
    /// Join the namespace and repository name with `/`, preserving observed casing.
    pub fn full_name(&self) -> String {
        format!("{}/{}", self.namespace, self.name)
    }
    /// Construct the canonical HTTPS web root from the stored reference.
    ///
    /// Call [`Self::parse`] first when the components originate in untrusted input.
    pub fn url(&self) -> String {
        format!("https://{}/{}", self.provider.host(), self.full_name())
    }
}

/// Parse a bounded HTTP(S) destination without credentials.
///
/// Returns `None` for URLs over 2,048 bytes, whitespace/control characters,
/// backslashes, missing hosts, credentials or port zero. Unlike [`RepositoryRef::parse`],
/// this accepts other hosts, paths, query strings, fragments and nonzero ports.
/// It validates syntax only and does not establish that a URL is safe to fetch.
pub fn web_url(value: &str) -> Option<Url> {
    let value = value.trim();
    if value.len() > 2048
        || value
            .chars()
            .any(|c| c.is_whitespace() || c.is_control() || c == '\\')
    {
        return None;
    }
    let url = Url::parse(value).ok()?;
    if !matches!(url.scheme(), "https" | "http")
        || url.host_str().is_none()
        || !url.username().is_empty()
        || url.password().is_some()
        || url.port() == Some(0)
    {
        return None;
    }
    Some(url)
}
