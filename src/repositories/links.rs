//! Extract CommonMark and HTML destinations as inert repository evidence.
//!
//! [`build`] never fetches link targets. It bounds scanning and extraction, ignores
//! code/hidden content and image sources, and deduplicates normalized destinations.

use super::{Link, LinkKind, web_url};
use pulldown_cmark::{Parser, html};
use scraper::Html;
use std::collections::HashSet;
use url::Url;

/// Whether an HTML node is code, executable/hidden markup or explicitly hidden.
fn hidden(node: &scraper::Node) -> bool {
    node.as_element().is_some_and(|e| {
        matches!(
            e.name(),
            "code" | "pre" | "script" | "style" | "textarea" | "template"
        ) || e.attr("hidden").is_some()
            || e.attr("aria-hidden") == Some("true")
    })
}
/// Build a deduplication key by normalizing trailing path slashes.
fn key(url: &Url) -> String {
    let mut normalized = url.clone();
    let path = url.path().trim_end_matches('/');
    normalized.set_path(if path.is_empty() { "/" } else { path });
    normalized.to_string()
}
/// Classify a destination using known hosts, paths and visible label words.
///
/// This is an eligibility heuristic over inspected evidence, not a network check.
fn classify(url: &Url, label: &str) -> LinkKind {
    let host = url.host_str().unwrap_or("");
    let path = url.path().to_ascii_lowercase();
    let words: Vec<_> = label
        .split(|c: char| !c.is_ascii_alphanumeric())
        .map(str::to_ascii_lowercase)
        .collect();
    let has = |terms: &[&str]| words.iter().any(|word| terms.contains(&word.as_str()));
    if host == "play.google.com" && path == "/store/apps/details" {
        LinkKind::AppStore
    } else if (host == "f-droid.org" && path.starts_with("/packages/"))
        || (host == "apt.izzysoft.de" && path.starts_with("/fdroid/index/apk/"))
    {
        LinkKind::PackageRepository
    } else if (host == "github.com" && path.split('/').nth(3) == Some("releases"))
        || (host == "gitlab.com"
            && (path.contains("/-/releases/") || path.ends_with("/-/releases")))
    {
        LinkKind::Release
    } else if matches!(host, "github.com" | "gitlab.com") && path.ends_with("/issues") {
        LinkKind::Support
    } else if matches!(
        host,
        "ko-fi.com" | "opencollective.com" | "www.buymeacoffee.com"
    ) || has(&["donate", "donation", "fund", "sponsor", "sponsors"])
    {
        LinkKind::Donation
    } else if has(&["docs", "documentation", "guide", "manual", "wiki"])
        || path
            .split('/')
            .any(|s| matches!(s, "docs" | "documentation" | "guide" | "manual" | "wiki"))
    {
        LinkKind::Documentation
    } else if has(&["help", "issues", "support"]) {
        LinkKind::Support
    } else {
        LinkKind::Other
    }
}
/// Build deduplicated evidence links without visiting their destinations.
///
/// Always inserts `repository`, then optional `release` and `website` links. Scans
/// at most 50,000 README characters and adds at most 20 unique README destinations
/// with IDs `readme-1` through `readme-20`. Code, hidden markup and image sources
/// are excluded; image alt text can label an enclosing link. Relative destinations
/// resolve against the inspected README URL or a provider-specific fallback.
pub fn build(
    root: Url,
    release: Option<&Url>,
    homepage: Option<Url>,
    readme: Option<&str>,
    readme_url: Option<&Url>,
) -> Vec<Link> {
    let mut known = HashSet::from([key(&root)]);
    let mut links = vec![Link {
        id: "repository".into(),
        label: "Repository".into(),
        url: root.clone(),
        kind: LinkKind::Repository,
    }];
    for (id, label, url, kind) in [
        (
            "release",
            "Latest release",
            release.cloned(),
            LinkKind::Release,
        ),
        ("website", "Website", homepage, LinkKind::Website),
    ] {
        if let Some(url) = url
            && known.insert(key(&url))
        {
            links.push(Link {
                id: id.into(),
                label: label.into(),
                url,
                kind,
            });
        }
    }
    let Some(readme) = readme else {
        return links;
    };
    let bounded: String = readme.chars().take(50_000).collect();
    let mut rendered = String::new();
    html::push_html(&mut rendered, Parser::new(&bounded));
    let document = Html::parse_fragment(&rendered);
    let fallback = format!(
        "{}/{}blob/HEAD/README.md",
        root.as_str().trim_end_matches('/'),
        if root.host_str() == Some("gitlab.com") {
            "-/"
        } else {
            ""
        }
    );
    let base = readme_url
        .cloned()
        .or_else(|| Url::parse(&fallback).ok())
        .unwrap_or(root.clone());
    let mut count = 0;
    let mut add = |destination: &str, label: String| {
        if count >= 20
            || destination
                .chars()
                .any(|c| c.is_control() || c.is_whitespace() || c == '\\')
        {
            return false;
        }
        let resolved = if destination.starts_with('#') {
            root.join(destination)
        } else {
            base.join(destination)
        };
        let Some(url) = resolved.ok().and_then(|url| web_url(url.as_str())) else {
            return false;
        };
        if !known.insert(key(&url)) {
            return false;
        }
        count += 1;
        let label = label.split_whitespace().collect::<Vec<_>>().join(" ");
        let label = if label.is_empty() || label.starts_with("http") {
            format!("{}{}", url.host_str().unwrap_or(""), url.path())
        } else {
            label
        };
        let label: String = label.chars().take(120).collect();
        let kind = classify(&url, &label);
        links.push(Link {
            id: format!("readme-{count}"),
            label,
            url,
            kind,
        });
        count == 20
    };
    // Enter/exit frames visit each visible node once and skip hidden subtrees.
    // Anchor labels are accumulated during that same traversal.
    let mut pending = vec![(document.tree.root(), false)];
    let mut anchors: Vec<(Option<&str>, String)> = Vec::new();
    while let Some((node, exiting)) = pending.pop() {
        if hidden(node.value()) {
            continue;
        }
        let element = node.value().as_element();
        let is_anchor = element.is_some_and(|element| element.name() == "a");
        if exiting {
            if is_anchor && let Some((href, label)) = anchors.pop() {
                if let Some((_, parent)) = anchors.last_mut() {
                    parent.push_str(&label);
                }
                if let Some(href) = href
                    && add(href, label)
                {
                    break;
                }
            }
            continue;
        }
        pending.push((node, true));
        pending.extend(node.children().rev().map(|child| (child, false)));
        if let Some(element) = element {
            if is_anchor {
                anchors.push((element.attr("href"), String::new()));
            } else if element.name() == "img"
                && let Some((_, label)) = anchors.last_mut()
            {
                label.push_str(element.attr("alt").unwrap_or(""));
            }
        }
        if let Some(text) = node.value().as_text() {
            if let Some((_, label)) = anchors.last_mut() {
                label.push_str(text);
                continue;
            }
            for word in text
                .split_whitespace()
                .filter(|s| s.starts_with("https://") || s.starts_with("http://"))
            {
                let mut value = word.trim_end_matches(['.', ',', ';', ':', '!', '?']);
                for (open, close) in [('(', ')'), ('[', ']'), ('{', '}')] {
                    let excess = value
                        .matches(close)
                        .count()
                        .saturating_sub(value.matches(open).count());
                    for _ in 0..excess {
                        if !value.ends_with(close) {
                            break;
                        }
                        value = &value[..value.len() - 1];
                    }
                }
                if add(value, value.into()) {
                    return links;
                }
            }
        }
    }
    links
}
