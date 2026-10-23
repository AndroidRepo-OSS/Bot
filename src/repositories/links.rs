//! Parse CommonMark as inert HTML; never fetch a README destination.
use super::{Link, LinkKind, web_url};
use pulldown_cmark::{Parser, html};
use scraper::{ElementRef, Html};
use std::collections::HashSet;
use url::Url;

fn hidden(node: &scraper::Node) -> bool {
    node.as_element().is_some_and(|e| {
        matches!(
            e.name(),
            "code" | "pre" | "script" | "style" | "textarea" | "template"
        ) || e.attr("hidden").is_some()
            || e.attr("aria-hidden") == Some("true")
    })
}
fn key(url: &Url) -> String {
    let mut normalized = url.clone();
    let path = url.path().trim_end_matches('/');
    normalized.set_path(if path.is_empty() { "/" } else { path });
    normalized.to_string()
}
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
            return;
        }
        let resolved = if destination.starts_with('#') {
            root.join(destination)
        } else {
            base.join(destination)
        };
        let Some(url) = resolved.ok().and_then(|url| web_url(url.as_str())) else {
            return;
        };
        if !known.insert(key(&url)) {
            return;
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
    };
    for node in document.tree.nodes() {
        if node.ancestors().any(|ancestor| hidden(ancestor.value())) || hidden(node.value()) {
            continue;
        }
        if let Some(element) = ElementRef::wrap(node)
            && element.value().name() == "a"
        {
            if let Some(href) = element.value().attr("href") {
                let mut label = String::new();
                for descendant in element.descendants() {
                    if descendant
                        .ancestors()
                        .any(|ancestor| hidden(ancestor.value()))
                    {
                        continue;
                    }
                    if let Some(text) = descendant.value().as_text() {
                        label.push_str(text);
                    }
                    if let Some(e) = descendant.value().as_element()
                        && e.name() == "img"
                    {
                        label.push_str(e.attr("alt").unwrap_or(""));
                    }
                }
                add(href, label);
            }
        } else if let Some(text) = node.value().as_text() {
            if node
                .ancestors()
                .any(|a| a.value().as_element().is_some_and(|e| e.name() == "a"))
            {
                continue;
            }
            for word in text
                .split_whitespace()
                .filter(|s| s.starts_with("https://") || s.starts_with("http://"))
            {
                let mut value = word.trim_end_matches(['.', ',', ';', ':', '!', '?']);
                for (open, close) in [('(', ')'), ('[', ']'), ('{', '}')] {
                    while value.ends_with(close)
                        && value.matches(close).count() > value.matches(open).count()
                    {
                        value = &value[..value.len() - 1];
                    }
                }
                add(value, value.into());
            }
        }
    }
    links
}
