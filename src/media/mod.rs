//! Attributed banner generation with bounded blocking CPU work.
//!
//! [`render()`] holds a semaphore permit through NASA retrieval and decoding/rendering
//! on a blocking worker. Missing or invalid remote art uses bundled fallback bytes
//! with matching credit. [`render_offline`] offers synchronous offline composition.

mod nasa;
mod render;
use crate::error::{Error, Result};
use bytes::Bytes;
pub use render::{BannerRequest, render_offline};
use std::sync::Arc;
use tokio::sync::Semaphore;

/// Encoded image bytes and display metadata used for visible attribution.
///
/// NASA responses remain untrusted until bounded decoding succeeds. The renderer
/// replaces an undecodable image with bundled artwork and its matching credit.
pub struct Artwork {
    /// Encoded image bytes, decoded under renderer resource limits.
    pub bytes: Bytes,
    /// NASA archive ID or local fallback identifier.
    pub id: String,
    /// Artwork title displayed in banner metadata.
    pub title: String,
    /// Originating center displayed in banner metadata.
    pub center: String,
    /// Catalog date string; renderer displays the part preceding `T`.
    pub date: String,
    /// Visible artwork credit matched to the actual image source.
    pub credit: String,
}
/// Rendered 1920 × 1080 PNG and the artwork ID actually used.
pub struct Banner {
    /// Encoded RGB PNG ready for local output or staff photo upload.
    pub bytes: Vec<u8>,
    /// Identifier of the image actually rendered, including fallback selection.
    pub artwork: String,
}

/// Fetch optional NASA art and render under an owned concurrency permit.
///
/// The permit covers network retrieval and the entire blocking decode/render job.
/// Unavailable or undecodable remote artwork uses the attributed local fallback.
/// CPU work runs on `spawn_blocking`; dropping the awaiting future does not cancel
/// a blocking job that has already started, and that job retains its permit.
///
/// # Errors
///
/// Returns [`Error::Image`] if the semaphore is closed, the blocking task fails,
/// or rendering the banner and bundled assets fails.
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
