from asyncio import to_thread
from contextlib import ExitStack
from functools import cache
from importlib.resources import files
from io import BytesIO
from math import hypot
from random import Random
from time import perf_counter
from typing import TYPE_CHECKING, Literal

import structlog
from PIL import Image, ImageDraw, ImageEnhance, ImageFont, ImageOps

from androidrepo_bot.media.imaging import ArtworkDecodeError, decode_artwork, decode_png_asset
from androidrepo_bot.media.models import BannerImage, BannerRequest, SpaceArtwork
from androidrepo_bot.media.nasa import fetch_nasa_artwork

if TYPE_CHECKING:
    import aiohttp

logger = structlog.get_logger(__name__)

_WIDTH = 1_920
_HEIGHT = 1_080
_TEXT_X = 140
_TEXT_WIDTH = 760
_TITLE_Y = 90
_TITLE_MAX_HEIGHT = 280
_TITLE_MIN_SIZE = 58
_TITLE_MAX_SIZE = 180
_TITLE_SPACING = -6
_SCRIM_OPAQUE_END = 0.32
_SCRIM_TRANSPARENT_START = 0.72
_MIN_WRAPPED_WORDS = 2
_WHITE = (248, 248, 246, 255)
_MUTED = (189, 190, 194, 255)
_SUBTLE = (154, 156, 163, 230)
type FontWeight = Literal[400, 500, 600, 800]


async def render_banner(session: aiohttp.ClientSession, request: BannerRequest) -> BannerImage:
    started_at = perf_counter()
    log_context = {"provider": request.provider, "repository": request.repository}
    logger.debug("Banner render started", **log_context)
    artwork = await fetch_nasa_artwork(session)
    banner = await to_thread(_render_banner, request, artwork)
    logger.info(
        "Banner rendered",
        **log_context,
        duration_seconds=perf_counter() - started_at,
        artwork_id=banner.artwork_id,
        used_remote_artwork=artwork is not None,
    )
    return banner


def _render_banner(request: BannerRequest, artwork: SpaceArtwork | None) -> BannerImage:
    selected_artwork = artwork or _fallback_artwork()
    background, selected_artwork = _prepare_background(selected_artwork)
    with background:
        _draw_content(background, request, selected_artwork)
        content = _encode_png(background)

    return BannerImage(
        content=content,
        filename=f"{_filename_stem(request.project_name)}-banner.png",
        artwork_id=selected_artwork.identifier,
    )


def _encode_png(image: Image.Image) -> bytes:
    with image.convert("RGB") as rgb_image, BytesIO() as output:
        rgb_image.save(output, format="PNG", compress_level=7, optimize=True)
        return output.getvalue()


def _prepare_background(artwork: SpaceArtwork) -> tuple[Image.Image, SpaceArtwork]:
    try:
        source = decode_artwork(artwork.content)
    except ArtworkDecodeError:
        artwork = _fallback_artwork()
        source = decode_artwork(artwork.content)

    rng = Random()
    horizontal_focus = min(0.7, max(0.44, 0.57 + rng.uniform(-0.08, 0.08)))
    with ExitStack() as stack:
        stack.enter_context(source)
        fitted = stack.enter_context(
            ImageOps.fit(source, (_WIDTH, _HEIGHT), method=Image.Resampling.LANCZOS, centering=(horizontal_focus, 0.5))
        )
        colored = stack.enter_context(ImageEnhance.Color(fitted).enhance(0.9))
        contrasted = stack.enter_context(ImageEnhance.Contrast(colored).enhance(1.14))
        brightened = stack.enter_context(ImageEnhance.Brightness(contrasted).enhance(0.82))
        rgba = stack.enter_context(brightened.convert("RGBA"))
        cool_tint = stack.enter_context(Image.new("RGBA", rgba.size, (4, 6, 17, 34)))
        tinted = stack.enter_context(Image.alpha_composite(rgba, cool_tint))
        scrimmed = stack.enter_context(Image.alpha_composite(tinted, _left_scrim()))
        return Image.alpha_composite(scrimmed, _edge_vignette()), artwork


@cache
def _left_scrim() -> Image.Image:
    width = 400
    height = 225
    pixels: list[int] = []
    for x in range(width):
        position = x / (width - 1)
        if position <= _SCRIM_OPAQUE_END:
            alpha = 250
        elif position >= _SCRIM_TRANSPARENT_START:
            alpha = 0
        else:
            progress = (position - _SCRIM_OPAQUE_END) / (_SCRIM_TRANSPARENT_START - _SCRIM_OPAQUE_END)
            eased = progress * progress * (3 - 2 * progress)
            alpha = round(250 * (1 - eased))
        pixels.append(alpha)
    with (
        Image.frombytes("L", (width, height), bytes(pixels) * height) as mask,
        ImageOps.fit(mask, (_WIDTH, _HEIGHT), method=Image.Resampling.BILINEAR) as fitted_mask,
    ):
        layer = Image.new("RGBA", (_WIDTH, _HEIGHT), (0, 0, 0, 0))
        layer.putalpha(fitted_mask)
        return layer


@cache
def _edge_vignette() -> Image.Image:
    width, height = 400, 225
    values: list[int] = []
    for y in range(height):
        for x in range(width):
            distance = hypot((x / (width - 1) - 0.56) / 0.76, (y / (height - 1) - 0.5) / 0.72)
            values.append(round(min(92, max(0.0, distance - 0.62) * 160)))
    with (
        Image.frombytes("L", (width, height), bytes(values)) as mask,
        ImageOps.fit(mask, (_WIDTH, _HEIGHT), method=Image.Resampling.BILINEAR) as fitted_mask,
    ):
        layer = Image.new("RGBA", (_WIDTH, _HEIGHT), (0, 0, 0, 0))
        layer.putalpha(fitted_mask)
        return layer


def _draw_content(image: Image.Image, request: BannerRequest, artwork: SpaceArtwork) -> None:
    draw = ImageDraw.Draw(image)
    title, title_font = _fit_title(draw, request.project_name)
    title_box = draw.multiline_textbbox(
        (0, 0), title, font=title_font, spacing=_TITLE_SPACING, align="left", stroke_width=0
    )
    title_height = title_box[3] - title_box[1]
    draw.multiline_text(
        (_TEXT_X - title_box[0], _TITLE_Y - title_box[1]),
        title,
        font=title_font,
        fill=_WHITE,
        spacing=_TITLE_SPACING,
        align="left",
    )

    metadata_y = round(_TITLE_Y + title_height + 36)
    rows = (
        ("Artwork", artwork.title),
        ("Archive", artwork.identifier),
        ("Center", artwork.center),
        ("Date", _display_date(artwork.date_created)),
        ("Repository", request.repository),
        ("Stack", _stack_summary(request)),
    )
    _draw_metadata(draw, rows, y=metadata_y)
    _draw_android_signature(image, draw)
    _draw_credits(draw, artwork)


def _draw_metadata(draw: ImageDraw.ImageDraw, rows: tuple[tuple[str, str], ...], *, y: int) -> None:
    label_font = _font(22, 400)
    value_font = _font(22, 600)
    row_height = 33
    for index, (label, value) in enumerate(rows):
        baseline = y + index * row_height
        label_text = f"{label}  "
        draw.text((_TEXT_X, baseline), label_text, font=label_font, fill=_MUTED)
        label_width = draw.textlength(label_text, font=label_font)
        available_width = _TEXT_WIDTH - round(label_width)
        rendered_value = _ellipsize(draw, value, value_font, available_width)
        draw.text((_TEXT_X + label_width, baseline), rendered_value, font=value_font, fill=_WHITE)


def _draw_android_signature(image: Image.Image, draw: ImageDraw.ImageDraw) -> None:
    text_font = _font(48, 600)
    brand_y = 895
    draw.text((_TEXT_X, brand_y), "Android", font=text_font, fill=_WHITE)
    text_box = draw.textbbox((_TEXT_X, brand_y), "Android", font=text_font)
    with decode_png_asset(_asset_bytes("android-head_flat.png")) as icon:
        icon_height = 35
        icon_width = round(icon.width * icon_height / icon.height)
        with ImageOps.fit(icon, (icon_width, icon_height), method=Image.Resampling.LANCZOS) as fitted_icon:
            image.alpha_composite(fitted_icon, (round(text_box[2] + 17), brand_y + 13))
    attribution_font = _font(11, 400)
    draw.text(
        (_TEXT_X, 956),
        "The Android robot is reproduced or modified from work created and shared by Google",
        font=attribution_font,
        fill=_SUBTLE,
    )
    draw.text(
        (_TEXT_X, 972),
        "and used according to terms described in the Creative Commons 3.0 Attribution License.",
        font=attribution_font,
        fill=_SUBTLE,
    )


def _draw_credits(draw: ImageDraw.ImageDraw, artwork: SpaceArtwork) -> None:
    credit = f"Image: {artwork.credit} · {artwork.identifier}"
    draw.text((_WIDTH - 70, 1_020), credit, font=_font(15, 500), fill=_SUBTLE, anchor="ra")


def _fit_title(draw: ImageDraw.ImageDraw, title: str) -> tuple[str, ImageFont.ImageFont | ImageFont.FreeTypeFont]:
    variants = _title_variants(title)
    low = _TITLE_MIN_SIZE
    high = _TITLE_MAX_SIZE
    best: tuple[str, ImageFont.ImageFont | ImageFont.FreeTypeFont] | None = None
    while low <= high:
        size = (low + high) // 2
        font = _font(size, 800)
        fitting = next((variant for variant in variants if _title_fits(draw, variant, font)), None)
        if fitting is None:
            high = size - 1
        else:
            best = fitting, font
            low = size + 1
    if best is not None:
        return best

    font = _font(_TITLE_MIN_SIZE, 800)
    wrapped = _balanced_wrap(title)
    if "\n" not in wrapped:
        return _ellipsize(draw, title, font, _TEXT_WIDTH), font
    return "\n".join(_ellipsize(draw, line, font, _TEXT_WIDTH) for line in wrapped.splitlines()), font


def _title_variants(title: str) -> tuple[str, ...]:
    wrapped = _balanced_wrap(title)
    return (title,) if wrapped == title else (title, wrapped)


def _balanced_wrap(title: str) -> str:
    words = title.split()
    if len(words) < _MIN_WRAPPED_WORDS:
        return title
    candidates = (" ".join(words[:index]) + "\n" + " ".join(words[index:]) for index in range(1, len(words)))
    return min(candidates, key=lambda value: abs(len(value.split("\n")[0]) - len(value.split("\n")[1])))


def _title_fits(draw: ImageDraw.ImageDraw, title: str, font: ImageFont.ImageFont | ImageFont.FreeTypeFont) -> bool:
    box = draw.multiline_textbbox((0, 0), title, font=font, spacing=_TITLE_SPACING)
    return box[2] - box[0] <= _TEXT_WIDTH and box[3] - box[1] <= _TITLE_MAX_HEIGHT


def _ellipsize(
    draw: ImageDraw.ImageDraw, value: str, font: ImageFont.ImageFont | ImageFont.FreeTypeFont, width: int
) -> str:
    if draw.textlength(value, font=font) <= width:
        return value
    low = 0
    high = len(value)
    best = "…"
    while low <= high:
        length = (low + high) // 2
        candidate = f"{value[:length].rstrip()}…"
        if draw.textlength(candidate, font=font) <= width:
            best = candidate
            low = length + 1
        else:
            high = length - 1
    return best


def _font(size: int, weight: FontWeight) -> ImageFont.FreeTypeFont:
    font = ImageFont.truetype(BytesIO(_asset_bytes("Figtree.ttf")), size)
    font.set_variation_by_axes([weight])
    return font


@cache
def _asset_bytes(name: str) -> bytes:
    return files("androidrepo_bot.media").joinpath("assets", name).read_bytes()


@cache
def _fallback_artwork() -> SpaceArtwork:
    return SpaceArtwork(
        content=_asset_bytes("black-hole-fallback.webp"),
        identifier="local-black-hole",
        title="Synthetic black-hole study",
        center="Android Repository",
        date_created=None,
        credit="Generated with OpenAI",
    )


def _display_date(value: str | None) -> str:
    if value is None:
        return "Not cataloged"
    return value.partition("T")[0] or "Not cataloged"


def _stack_summary(request: BannerRequest) -> str:
    values = tuple(
        value
        for value in (
            request.primary_language,
            request.license_name,
            request.release,
            " · ".join(request.topics[:2]) or None,
        )
        if value is not None
    )
    return " · ".join(values) or f"{request.provider} project"


def _filename_stem(title: str) -> str:
    stem = "".join(character.lower() if character.isalnum() else "-" for character in title)
    return "-".join(filter(None, stem.split("-")))[:80] or "project"
