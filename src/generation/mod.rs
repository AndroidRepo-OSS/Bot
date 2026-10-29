//! Structured model results validated against one public evidence snapshot.
//!
//! [`GeneratedPost`] is untrusted JSON until [`GeneratedPost::resolve`] checks text,
//! counts, tags and link IDs. [`Draft`] carries resolved URLs, while [`Outcome`] also
//! represents non-Android, insufficient-evidence and missing-download decisions.
//! The caller supplies trusted staff approval separately from repository content.

mod client;
mod prompt;
mod tags;
use crate::repositories::Repository;
pub use client::generate;
use serde::{Deserialize, Serialize};
use url::Url;

/// A plain-text label and final URL resolved from inspected repository evidence.
#[derive(Clone, Debug, Serialize)]
pub struct PostLink {
    /// Validated plain-text caption label.
    pub label: String,
    /// Final destination copied from inspected evidence.
    pub url: Url,
}
/// Validated content prepared for staff review, with evidence-resolved destinations.
///
/// [`GeneratedPost::resolve`] validates model output; the consumer validator supplied
/// to [`generate`] checks the assembled presentation on each attempt. Direct field
/// construction does not validate it.
#[derive(Clone, Debug, Serialize)]
pub struct Draft {
    /// Plain-text project name, at most 100 Unicode scalar values.
    pub title: String,
    /// Plain-text summary, at most 280 Unicode scalar values.
    pub summary: String,
    /// Three to five distinct features, each at most 90 Unicode scalar values.
    pub features: Vec<String>,
    /// Mandatory repository link followed by validated optional destinations.
    pub links: Vec<PostLink>,
    /// Eligible inspected download destination, absent only under approved policy.
    pub download_url: Option<Url>,
    /// One to three exact supported categories without leading hashtag markers.
    pub tags: Vec<String>,
}
/// Untrusted model-selected evidence ID and proposed plain-text label.
///
/// Unknown JSON fields are rejected; final URLs are supplied only during resolution.
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct GeneratedLink {
    /// Untrusted exact evidence ID proposed by the model.
    id: String,
    /// Untrusted label awaiting plain-text validation.
    label: String,
}
/// Strict JSON tool output before semantic validation.
///
/// Deserialization rejects unknown fields and requires `download_link_id` even when
/// its value is `null`. [`Self::resolve`] checks text, tags and destination eligibility.
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct GeneratedPost {
    /// Untrusted proposed project title.
    project_name: String,
    /// Untrusted proposed summary.
    summary: String,
    /// Untrusted proposed feature list.
    features: Vec<String>,
    /// Untrusted optional destination IDs and labels.
    links: Vec<GeneratedLink>,
    /// Required nullable selection; null needs staff approval and absent candidates.
    #[serde(deserialize_with = "Option::deserialize")]
    download_link_id: Option<String>,
    /// Untrusted proposed category strings requiring exact allowlist membership.
    tags: Vec<String>,
}
/// Strict JSON explanation for a non-draft generation outcome.
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Reason {
    /// Untrusted explanation awaiting the 280-character plain-text check.
    reason: String,
}
/// One of the four accepted structured model results.
///
/// A missing-download decision requires a separate staff approval before retrying
/// without a Download button; it is distinct from insufficient repository evidence.
pub enum Outcome {
    /// Validated post content ready for staff review.
    Draft(Draft),
    /// Evidence indicates the project is outside Android scope, with a safe reason.
    NotAndroid(String),
    /// Evidence cannot support a complete grounded draft, with a safe reason.
    Insufficient(String),
    /// No eligible download exists and staff approval is still required.
    MissingDownload(String),
}

/// Safe validation categories used to build corrective instructions without external text.
#[derive(Clone, Copy, Debug)]
enum Rejection {
    /// The response did not select exactly one recognized output tool.
    Tool,
    /// Tool arguments did not match the declared JSON schema.
    Schema,
    /// Generation exhausted its output token limit.
    Truncated,
    /// A field is empty or exceeds its character limit.
    TextLength,
    /// A field contains forbidden formatting or delimiters.
    TextFormat,
    /// Feature count or uniqueness violates the draft contract.
    Features,
    /// Tags violate the count, uniqueness or allowlist requirements.
    Tags,
    /// Optional link count, uniqueness or eligibility is invalid.
    Links,
    /// Download selection or missing-download outcome violates staff policy.
    Download,
    /// Combined content exceeds the draft character budget.
    ContentLength,
    /// The assembled caption failed the consumer's presentation check.
    Caption,
}
impl Rejection {
    /// Return a trusted, specific correction; never interpolate rejected model output.
    fn correction(self) -> &'static str {
        match self {
            Self::Tool => {
                "Return exactly one recognized output tool, never free-form text or multiple calls."
            }
            Self::Schema => {
                "Return valid JSON arguments matching every required field and type in the selected tool schema; omit unknown fields."
            }
            Self::Truncated => {
                "The output was truncated. Return a shorter complete result within 2048 output tokens."
            }
            Self::TextLength => {
                "Keep all text nonempty and within its field limit: name 100, summary/reason 280, each feature 90 and link label 60 characters."
            }
            Self::TextFormat => {
                "Use bounded plain text without URLs, markup, hashtags, emoji, bullet prefixes or delimiter characters; keep the project name on one line."
            }
            Self::Features => {
                "Return 3–5 distinct evidence-supported features; do not repeat the same capability."
            }
            Self::Tags => {
                "Return 1–3 distinct tags using exact entries from the declared tag enum."
            }
            Self::Links => {
                "Return at most four distinct eligible optional link IDs from the supplied evidence; exclude repository, donation and the selected download destination."
            }
            Self::Download => {
                "Select an exact verified download-candidate ID. Null requires no candidates and explicit staff approval; missing_download_source requires no candidates and no approval."
            }
            Self::ContentLength => {
                "Shorten the result: combined name, summary, features, repository label, optional labels and hashtags must fit 950 characters."
            }
            Self::Caption => {
                "Shorten the result so the assembled caption fits 1024 UTF-16 units, including headings, separators and labels."
            }
        }
    }
}
/// Validation result retaining only a safe contract category.
type ValidationResult<T> = std::result::Result<T, Rejection>;

/// Normalize whitespace and validate a bounded plain-text model field.
///
/// `limit` counts Unicode scalar values, not bytes or UTF-16 units. Rejects empty
/// text, URL markers, formatting delimiters, bullet prefixes and specified symbol/emoji
/// ranges. This check does not prove factual accuracy or language.
///
/// # Errors
///
/// Returns a safe rejection category when normalized content violates the text contract.
fn validate_plain_text(value: &str, limit: usize) -> ValidationResult<String> {
    let value = value.split_whitespace().collect::<Vec<_>>().join(" ");
    let lowercase = value.to_lowercase();
    if value.is_empty() || value.chars().count() > limit {
        return Err(Rejection::TextLength);
    }
    if lowercase.contains("http://") || lowercase.contains("https://") || lowercase.contains("www.")
        || value.contains(['<', '>', '`', '#']) || value.contains("**") || value.contains("__") || value.contains("~~") || value.contains("](")
        || value.chars().any(|c| matches!(c, '\u{2022}' | '\u{2023}' | '\u{2043}' | '\u{25aa}' | '\u{25ab}' | '\u{25e6}' | '\u{2600}'..='\u{27bf}' | '\u{1f000}'..='\u{1faff}'))
        || ["- ", "+ ", "* "].iter().any(|prefix| value.starts_with(prefix)) {
        return Err(Rejection::TextFormat);
    }
    Ok(value)
}
/// Check uniqueness after Unicode lowercasing without altering the original values.
fn distinct<'a>(values: impl Iterator<Item = &'a str>) -> bool {
    let mut seen = std::collections::HashSet::new();
    values
        .map(str::to_lowercase)
        .all(|value| seen.insert(value))
}
impl GeneratedPost {
    /// Resolve a model post against the same inspected repository snapshot.
    ///
    /// Requires 3–5 distinct features, 1–3 supported distinct tags, at most four optional
    /// links and a 950-character content budget. Inserts the mandatory repository link;
    /// optional selections exclude repository/donation links and the selected download.
    /// `allow_missing` is staff approval, and only permits a null download when the
    /// snapshot has no eligible download candidate. It does not permit invented URLs.
    ///
    /// # Errors
    ///
    /// Returns a safe rejection category for invalid text, counts, duplicates, tags, link IDs,
    /// destination categories, missing mandatory/download evidence or excessive content.
    fn resolve(self, repository: &Repository, allow_missing: bool) -> ValidationResult<Draft> {
        if self.project_name.contains(['\r', '\n', '\t']) {
            return Err(Rejection::TextFormat);
        }
        if !(3..=5).contains(&self.features.len()) {
            return Err(Rejection::Features);
        }
        if !(1..=3).contains(&self.tags.len()) {
            return Err(Rejection::Tags);
        }
        if self.links.len() > 4 {
            return Err(Rejection::Links);
        }
        let title = validate_plain_text(&self.project_name, 100)?;
        let summary = validate_plain_text(&self.summary, 280)?;
        let features: Vec<_> = self
            .features
            .iter()
            .map(|v| validate_plain_text(v, 90))
            .collect::<ValidationResult<_>>()?;
        if !distinct(features.iter().map(String::as_str)) {
            return Err(Rejection::Features);
        }
        if !distinct(self.tags.iter().map(String::as_str))
            || self.tags.iter().any(|t| !tags::TAGS.contains(&t.as_str()))
        {
            return Err(Rejection::Tags);
        }
        let download_url = match self.download_link_id.as_deref() {
            Some(id) => Some(
                repository
                    .link(id)
                    .filter(|link| link.kind.is_download_candidate())
                    .ok_or(Rejection::Download)?
                    .url
                    .clone(),
            ),
            None if allow_missing && !repository.has_download() => None,
            None => return Err(Rejection::Download),
        };
        let mandatory = repository.link("repository").ok_or(Rejection::Links)?;
        let mut links = vec![PostLink {
            label: "Repository".into(),
            url: mandatory.url.clone(),
        }];
        if !distinct(self.links.iter().map(|link| link.id.as_str())) {
            return Err(Rejection::Links);
        }
        for selected in self.links {
            if Some(&selected.id) == self.download_link_id.as_ref() {
                return Err(Rejection::Links);
            }
            let link = repository
                .link(&selected.id)
                .filter(|link| link.kind.is_optional_destination())
                .ok_or(Rejection::Links)?;
            links.push(PostLink {
                label: validate_plain_text(&selected.label, 60)?,
                url: link.url.clone(),
            });
        }
        let length = title.chars().count()
            + summary.chars().count()
            + features.iter().map(|v| v.chars().count()).sum::<usize>()
            + links.iter().map(|v| v.label.chars().count()).sum::<usize>()
            + self
                .tags
                .iter()
                .map(|v| v.chars().count() + 1)
                .sum::<usize>();
        if length > 950 {
            return Err(Rejection::ContentLength);
        }
        Ok(Draft {
            title,
            summary,
            features,
            links,
            download_url,
            tags: self.tags,
        })
    }
}
