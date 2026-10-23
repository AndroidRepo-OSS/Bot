//! Bounded structured generation. Only inspected link IDs can become destinations.
mod client;
mod prompt;
mod tags;
use crate::{
    error::{Error, Result},
    repositories::Repository,
};
pub use client::generate;
use serde::{Deserialize, Serialize};
use url::Url;

#[derive(Clone, Debug, Serialize)]
pub struct PostLink {
    pub label: String,
    pub url: Url,
}
#[derive(Clone, Debug, Serialize)]
pub struct Draft {
    pub title: String,
    pub summary: String,
    pub features: Vec<String>,
    pub links: Vec<PostLink>,
    pub download_url: Option<Url>,
    pub tags: Vec<String>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct GeneratedLink {
    id: String,
    label: String,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct GeneratedPost {
    project_name: String,
    summary: String,
    features: Vec<String>,
    links: Vec<GeneratedLink>,
    #[serde(deserialize_with = "Option::deserialize")]
    download_link_id: Option<String>,
    tags: Vec<String>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Reason {
    reason: String,
}
pub enum Outcome {
    Draft(Draft),
    NotAndroid(String),
    Insufficient(String),
    MissingDownload(String),
}

pub fn validate_plain_text(value: &str, limit: usize) -> Result<String> {
    let value = value.split_whitespace().collect::<Vec<_>>().join(" ");
    let lowercase = value.to_lowercase();
    if value.is_empty() || value.chars().count() > limit || lowercase.contains("http://") || lowercase.contains("https://") || lowercase.contains("www.")
        || value.contains(['<', '>', '`', '#']) || value.contains("**") || value.contains("__") || value.contains("~~") || value.contains("](")
        || value.chars().any(|c| matches!(c, '\u{2022}' | '\u{2023}' | '\u{2043}' | '\u{25aa}' | '\u{25ab}' | '\u{25e6}' | '\u{2600}'..='\u{27bf}' | '\u{1f000}'..='\u{1faff}'))
        || ["- ", "+ ", "* "].iter().any(|prefix| value.starts_with(prefix)) {
        return Err(Error::Generation);
    }
    Ok(value)
}
fn distinct<'a>(values: impl Iterator<Item = &'a str>) -> bool {
    let mut seen = std::collections::HashSet::new();
    values
        .map(str::to_lowercase)
        .all(|value| seen.insert(value))
}
impl GeneratedPost {
    pub fn resolve(self, repository: &Repository, allow_missing: bool) -> Result<Draft> {
        if self.project_name.contains(['\r', '\n', '\t'])
            || !(3..=5).contains(&self.features.len())
            || !(1..=3).contains(&self.tags.len())
            || self.links.len() > 4
        {
            return Err(Error::Generation);
        }
        let title = validate_plain_text(&self.project_name, 100)?;
        let summary = validate_plain_text(&self.summary, 280)?;
        let features: Vec<_> = self
            .features
            .iter()
            .map(|v| validate_plain_text(v, 90))
            .collect::<Result<_>>()?;
        if !distinct(features.iter().map(String::as_str))
            || !distinct(self.tags.iter().map(String::as_str))
            || self.tags.iter().any(|t| !tags::TAGS.contains(&t.as_str()))
        {
            return Err(Error::Generation);
        }
        let download_url = match self.download_link_id.as_deref() {
            Some(id) => Some(
                repository
                    .link(id)
                    .filter(|link| link.kind.is_download_candidate())
                    .ok_or(Error::Generation)?
                    .url
                    .clone(),
            ),
            None if allow_missing && !repository.has_download() => None,
            None => return Err(Error::Generation),
        };
        let mandatory = repository.link("repository").ok_or(Error::Generation)?;
        let mut links = vec![PostLink {
            label: "Repository".into(),
            url: mandatory.url.clone(),
        }];
        if !distinct(self.links.iter().map(|link| link.id.as_str())) {
            return Err(Error::Generation);
        }
        for selected in self.links {
            if Some(&selected.id) == self.download_link_id.as_ref() {
                return Err(Error::Generation);
            }
            let link = repository
                .link(&selected.id)
                .filter(|link| link.kind.is_optional_destination())
                .ok_or(Error::Generation)?;
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
            return Err(Error::Generation);
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
