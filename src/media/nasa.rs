use super::Artwork;
use crate::{
    error::{Error, Result},
    http,
    repositories::web_url,
};
use bytes::Bytes;
use reqwest::Client;
use serde::Deserialize;
use std::{collections::HashSet, time::Duration};

const IDS: &[&str] = &[
    "PIA22085",
    "PIA22355",
    "PIA12966",
    "PIA13168",
    "PIA01884",
    "PIA16695",
    "PIA14730",
    "PIA25434",
    "PIA09108",
    "PIA25433",
    "PIA13442",
    "PIA13451",
    "PIA13128",
    "PIA13448",
    "PIA17553",
    "PIA14417",
    "PIA15658",
    "PIA07902",
    "PIA04200",
    "PIA05062",
    "PIA03606",
    "PIA09178",
    "PIA26601",
    "GSFC_20171208_Archive_e002172",
    "PIA23689",
    "PIA23690",
    "PIA04921",
    "PIA15656",
    "PIA04629",
    "PIA04624",
    "PIA08787",
    "PIA04630",
    "PIA07903",
    "PIA04628",
    "PIA04213",
    "PIA04218",
    "PIA07828",
];
#[derive(Deserialize)]
struct Payload {
    collection: Collection,
}
#[derive(Deserialize)]
struct Collection {
    items: Vec<Item>,
}
#[derive(Deserialize)]
struct Item {
    #[serde(default)]
    data: Vec<Data>,
    #[serde(default)]
    links: Vec<Link>,
    href: Option<String>,
}
#[derive(Deserialize)]
struct Data {
    nasa_id: String,
    title: String,
    center: Option<String>,
    date_created: Option<String>,
}
#[derive(Deserialize)]
struct Link {
    rel: Option<String>,
    href: Option<String>,
}
fn asset_url(value: &str) -> Option<String> {
    let mut url = web_url(value)?;
    let authority = value.split_once("://")?.1.split('/').next()?;
    if url.host_str() != Some("images-assets.nasa.gov") || authority.contains(':') {
        return None;
    }
    url.set_scheme("https").ok()?;
    Some(url.into())
}
async fn read(client: &Client, url: &str, image: bool) -> Result<Bytes> {
    let response = client
        .get(url)
        .timeout(Duration::from_secs(8))
        .send()
        .await?;
    if !response.status().is_success() {
        return Err(Error::External);
    }
    let content_type = response
        .headers()
        .get("content-type")
        .and_then(|v| v.to_str().ok())
        .unwrap_or("")
        .split(';')
        .next()
        .unwrap_or("");
    if (image
        && !matches!(
            content_type,
            "image/jpeg" | "image/png" | "image/webp" | "image/tiff"
        ))
        || (!image && content_type != "application/json")
    {
        return Err(Error::Payload);
    }
    http::bounded(
        response,
        if image {
            12 * 1024 * 1024
        } else {
            http::METADATA_LIMIT
        },
    )
    .await
}
pub async fn fetch(client: &Client) -> Option<Artwork> {
    let id = IDS[rand::random_range(0..IDS.len())];
    match tokio::time::timeout(Duration::from_secs(20), load(client, id)).await {
        Ok(Ok(artwork)) => Some(artwork),
        _ => {
            tracing::warn!("NASA artwork unavailable; using bundled fallback");
            None
        }
    }
}
async fn load(client: &Client, id: &str) -> Result<Artwork> {
    let payload: Payload = serde_json::from_slice(
        &read(
            client,
            &format!("https://images-api.nasa.gov/search?nasa_id={id}&media_type=image"),
            false,
        )
        .await?,
    )?;
    let item = payload
        .collection
        .items
        .into_iter()
        .next()
        .ok_or(Error::Payload)?;
    let metadata = item.data.into_iter().next().ok_or(Error::Payload)?;
    if metadata.nasa_id != id
        || metadata.title.trim().is_empty()
        || metadata.title.chars().count() > 500
        || metadata
            .center
            .as_ref()
            .is_some_and(|v| v.chars().count() > 200)
        || metadata
            .date_created
            .as_ref()
            .is_some_and(|v| v.len() > 100)
    {
        return Err(Error::Payload);
    }
    let preview = item
        .links
        .iter()
        .find(|link| link.rel.as_deref() == Some("preview"))
        .and_then(|link| link.href.as_deref())
        .and_then(asset_url)
        .ok_or(Error::Payload)?;
    let payload: Payload = serde_json::from_slice(
        &read(
            client,
            &format!("https://images-api.nasa.gov/asset/{id}"),
            false,
        )
        .await?,
    )?;
    let mut urls: Vec<_> = payload
        .collection
        .items
        .iter()
        .filter_map(|i| i.href.as_deref())
        .filter_map(asset_url)
        .filter(|url| {
            url::Url::parse(url).ok().is_some_and(|url| {
                [".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff"]
                    .iter()
                    .any(|ext| url.path().to_ascii_lowercase().ends_with(ext))
            })
        })
        .collect();
    urls.sort_by_key(|url| {
        if url.contains("~large.") {
            0
        } else if url.contains("~medium.") {
            1
        } else if url.contains("~orig.") {
            2
        } else {
            3
        }
    });
    urls.push(preview);
    let mut seen = HashSet::new();
    for url in urls
        .into_iter()
        .filter(|url| seen.insert(url.clone()))
        .take(8)
    {
        if let Ok(bytes) = read(client, &url, true).await {
            let center = metadata
                .center
                .filter(|v| !v.trim().is_empty())
                .unwrap_or_else(|| "NASA".into());
            let credit = match center.to_ascii_lowercase().as_str() {
                "jpl" => "NASA/JPL-Caltech".into(),
                "gsfc" => "NASA/GSFC".into(),
                "jsc" => "NASA/JSC".into(),
                "nasa" => "NASA".into(),
                _ => format!("NASA/{center}"),
            };
            return Ok(Artwork {
                bytes,
                id: id.into(),
                title: metadata.title,
                center,
                date: metadata
                    .date_created
                    .unwrap_or_else(|| "Not cataloged".into()),
                credit,
            });
        }
    }
    Err(Error::Image)
}
