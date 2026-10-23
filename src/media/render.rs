//! Synchronous image decoding, text layout and attributed PNG composition.
//!
//! Decoder limits bound untrusted artwork; invalid remote bytes use the local
//! fallback. Output always includes Android robot and artwork attribution. Async
//! callers use [`super::render()`] to move CPU work onto a bounded blocking worker.

use super::{Artwork, Banner};
use crate::error::{Error, Result};
use ab_glyph::{FontRef, VariableFont};
use image::{
    DynamicImage, ImageDecoder, ImageEncoder, ImageReader, Rgba, RgbaImage,
    codecs::png::{CompressionType, FilterType as PngFilter, PngEncoder},
    imageops::{self, FilterType},
};
use imageproc::drawing::{draw_text_mut, text_size};
use std::io::Cursor;

/// Embedded Figtree variable font; license inventory lives in `assets/README.md`.
const FONT: &[u8] = include_bytes!("assets/Figtree.ttf");
/// Embedded synthetic black-hole image with generated-artwork attribution.
const FALLBACK: &[u8] = include_bytes!("assets/black-hole-fallback.webp");
/// Embedded Google Android robot artwork requiring visible CC BY 3.0 attribution.
const ANDROID: &[u8] = include_bytes!("assets/android-head_flat.png");
/// Output banner width in pixels.
const WIDTH: u32 = 1920;
/// Output banner height in pixels.
const HEIGHT: u32 = 1080;
/// Primary text color in RGBA.
const WHITE: Rgba<u8> = Rgba([248, 248, 246, 255]);
/// Secondary metadata and attribution text color in RGBA.
const MUTED: Rgba<u8> = Rgba([189, 190, 194, 255]);

/// Text to lay out on a banner; rendering performs wrapping and pixel-width clipping.
///
/// This does not validate model content. Use validated draft text in the staff workflow.
pub struct BannerRequest {
    /// Project title wrapped and clipped to the banner title area.
    pub title: String,
    /// Observed repository name displayed in metadata.
    pub repository: String,
    /// Technology/license/release summary displayed in metadata.
    pub stack: String,
}
/// Pair bundled image bytes with their own metadata and generated-artwork credit.
fn fallback() -> Artwork {
    Artwork {
        bytes: bytes::Bytes::from_static(FALLBACK),
        id: "local-black-hole".into(),
        title: "Synthetic black-hole study".into(),
        center: "Android Repository".into(),
        date: "Not cataloged".into(),
        credit: "Generated with OpenAI".into(),
    }
}
/// Decode an allowed image format with allocation, dimension and pixel limits.
///
/// Allows JPEG, PNG, WebP and TIFF; caps decoder allocation at 256 MiB, dimensions
/// at 16,384 pixels per axis and image area at 40 million pixels. Applies orientation.
///
/// # Errors
///
/// Returns [`Error::Image`] for unsupported formats, exceeded limits or decode/
/// orientation failures.
fn decode(bytes: &[u8]) -> Result<DynamicImage> {
    let mut reader = ImageReader::new(Cursor::new(bytes))
        .with_guessed_format()
        .map_err(|_| Error::Image)?;
    if !matches!(
        reader.format(),
        Some(
            image::ImageFormat::Jpeg
                | image::ImageFormat::Png
                | image::ImageFormat::WebP
                | image::ImageFormat::Tiff
        )
    ) {
        return Err(Error::Image);
    }
    let mut limits = image::Limits::default();
    limits.max_alloc = Some(256 * 1024 * 1024);
    limits.max_image_width = Some(16_384);
    limits.max_image_height = Some(16_384);
    reader.limits(limits);
    let mut decoder = reader.into_decoder().map_err(|_| Error::Image)?;
    let (width, height) = decoder.dimensions();
    if u64::from(width) * u64::from(height) > 40_000_000 {
        return Err(Error::Image);
    }
    let orientation = decoder.orientation().map_err(|_| Error::Image)?;
    let mut decoded = DynamicImage::from_decoder(decoder).map_err(|_| Error::Image)?;
    decoded.apply_orientation(orientation);
    Ok(decoded)
}
/// Clip text at a Unicode scalar boundary until it and an ellipsis fit `max` pixels.
fn ellipsis(value: &str, font: &FontRef<'_>, size: f32, max: u32) -> String {
    if text_size(size, font, value).0 <= max {
        return value.into();
    }
    let mut value = value.to_owned();
    while !value.is_empty() {
        value.pop();
        if text_size(size, font, &format!("{value}…")).0 <= max {
            return format!("{value}…");
        }
    }
    String::new()
}
/// Wrap whitespace-separated title words into lines targeting 760 pixels.
///
/// Individual oversized words remain intact for subsequent font sizing and clipping.
fn lines(value: &str, font: &FontRef<'_>, size: f32) -> Vec<String> {
    let mut lines = Vec::new();
    let mut line = String::new();
    for word in value.split_whitespace() {
        let candidate = if line.is_empty() {
            word.into()
        } else {
            format!("{line} {word}")
        };
        if text_size(size, font, &candidate).0 > 760 && !line.is_empty() {
            lines.push(line);
            line = word.into();
        } else {
            line = candidate;
        }
    }
    if !line.is_empty() {
        lines.push(line);
    }
    lines
}
/// Render a banner using only embedded artwork, font and Android assets.
///
/// Performs CPU work synchronously; async callers should use a bounded blocking
/// worker. See the crate-level CLI example for offline use without credentials.
///
/// # Errors
///
/// Returns [`Error::Image`] if bundled image/font decoding or PNG encoding fails.
pub fn render_offline(request: BannerRequest) -> Result<Banner> {
    render(request, None)
}
/// Compose an attributed 1920 × 1080 RGB PNG synchronously.
///
/// Uses bundled artwork when none is supplied or remote decoding fails. Wraps and
/// clips titles, renders metadata and keeps Android and artwork credits visible.
/// Call [`super::render()`] from async workflows to bound and offload CPU work.
///
/// # Errors
///
/// Returns [`Error::Image`] for failures decoding required bundled assets, loading
/// the font or encoding the PNG.
pub fn render(request: BannerRequest, artwork: Option<Artwork>) -> Result<Banner> {
    let mut artwork = artwork.unwrap_or_else(fallback);
    let source = match decode(&artwork.bytes) {
        Ok(image) => image,
        Err(_) => {
            artwork = fallback();
            decode(&artwork.bytes)?
        }
    };
    let mut image = source
        .resize_to_fill(WIDTH, HEIGHT, FilterType::Lanczos3)
        .into_rgba8();
    // One pass applies brightness, cool tint and a smooth left scrim; no full-size layers.
    for (x, y, pixel) in image.enumerate_pixels_mut() {
        let progress = ((x as f32 / WIDTH as f32 - 0.32) / 0.4).clamp(0.0, 1.0);
        let scrim = 0.98 * (1.0 - progress * progress * (3.0 - 2.0 * progress));
        let edge = (((x as f32 / WIDTH as f32 - 0.56) / 0.76)
            .hypot((y as f32 / HEIGHT as f32 - 0.5) / 0.72)
            - 0.62)
            .clamp(0.0, 0.6);
        for (channel, tint) in pixel.0[..3].iter_mut().zip([4.0, 6.0, 17.0]) {
            *channel = ((f32::from(*channel) * 0.72 + tint * 0.13)
                * (1.0 - scrim)
                * (1.0 - edge * 0.6)) as u8;
        }
    }
    let mut font = FontRef::try_from_slice(FONT).map_err(|_| Error::Image)?;
    font.set_variation(b"wght", 800.0);
    let mut size = 180.0;
    let title = loop {
        let wrapped = lines(&request.title, &font, size);
        if (wrapped.len() as f32 * size <= 280.0
            && wrapped
                .iter()
                .all(|line| text_size(size, &font, line).0 <= 760))
            || size <= 58.0
        {
            break wrapped;
        }
        size -= 2.0;
    };
    for (index, line) in title.iter().take(3).enumerate() {
        draw_text_mut(
            &mut image,
            WHITE,
            140,
            90 + (index as f32 * size) as i32,
            size,
            &font,
            &ellipsis(line, &font, size, 760),
        );
    }
    let y = 90 + (title.len().min(3) as f32 * size) as i32 + 36;
    font.set_variation(b"wght", 500.0);
    for (index, (label, value)) in [
        ("Artwork", artwork.title.as_str()),
        ("Archive", &artwork.id),
        ("Center", &artwork.center),
        (
            "Date",
            artwork.date.split('T').next().unwrap_or("Not cataloged"),
        ),
        ("Repository", &request.repository),
        ("Stack", &request.stack),
    ]
    .iter()
    .enumerate()
    {
        let prefix = format!("{label}  ");
        draw_text_mut(
            &mut image,
            MUTED,
            140,
            y + index as i32 * 33,
            26.0,
            &font,
            &prefix,
        );
        let label_width = text_size(26.0, &font, &prefix).0;
        draw_text_mut(
            &mut image,
            WHITE,
            140 + label_width as i32,
            y + index as i32 * 33,
            26.0,
            &font,
            &ellipsis(value, &font, 26.0, 760 - label_width),
        );
    }
    font.set_variation(b"wght", 600.0);
    draw_text_mut(&mut image, WHITE, 140, 895, 56.0, &font, "Android");
    let icon = decode(ANDROID)?
        .resize(72, 40, FilterType::Lanczos3)
        .into_rgba8();
    imageops::overlay(
        &mut image,
        &icon,
        140 + i64::from(text_size(56.0, &font, "Android").0) + 17,
        908,
    );
    font.set_variation(b"wght", 400.0);
    credit(
        &mut image,
        &font,
        140,
        960,
        "The Android robot is reproduced from work created and shared by Google",
    );
    credit(
        &mut image,
        &font,
        140,
        982,
        "and used under the Creative Commons 3.0 Attribution License.",
    );
    let attribution = ellipsis(
        &format!("Image: {} · {}", artwork.credit, artwork.id),
        &font,
        18.0,
        820,
    );
    credit(&mut image, &font, 960, 1000, &attribution);
    let rgb = DynamicImage::ImageRgba8(image).into_rgb8();
    let mut bytes = Vec::new();
    PngEncoder::new_with_quality(&mut bytes, CompressionType::Fast, PngFilter::Adaptive)
        .write_image(rgb.as_raw(), WIDTH, HEIGHT, image::ExtendedColorType::Rgb8)
        .map_err(|_| Error::Image)?;
    Ok(Banner {
        bytes,
        artwork: artwork.id,
    })
}
/// Draw an attribution line in the shared 18-pixel muted text style.
fn credit(image: &mut RgbaImage, font: &FontRef<'_>, x: i32, y: i32, text: &str) {
    draw_text_mut(image, MUTED, x, y, 18.0, font, text);
}
