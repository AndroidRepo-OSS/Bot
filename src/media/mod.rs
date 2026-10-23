//! Bounded artwork decoding and CPU rendering outside Tokio's I/O workers.
mod nasa;
mod render;
use crate::error::{Error, Result};
use bytes::Bytes;
pub use render::{BannerRequest, render_offline};
use std::sync::Arc;
use tokio::sync::Semaphore;

pub struct Artwork {
    pub bytes: Bytes,
    pub id: String,
    pub title: String,
    pub center: String,
    pub date: String,
    pub credit: String,
}
pub struct Banner {
    pub bytes: Vec<u8>,
    pub artwork: String,
}

pub async fn render(
    client: &reqwest::Client,
    slots: Arc<Semaphore>,
    request: BannerRequest,
) -> Result<Banner> {
    let permit = slots.acquire_owned().await.map_err(|_| Error::Image)?;
    let artwork = nasa::fetch(client).await;
    tokio::task::spawn_blocking(move || {
        let _permit = permit;
        render::render(request, artwork)
    })
    .await
    .map_err(|_| Error::Image)?
}
