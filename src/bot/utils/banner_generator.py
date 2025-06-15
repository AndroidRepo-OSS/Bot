# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations

import random
from collections.abc import Generator
from contextlib import contextmanager
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from typing import NamedTuple

from PIL import Image, ImageDraw, ImageFont

MATERIAL_COLORS = (
    "#1565C0",
    "#0D47A1",
    "#1976D2",
    "#283593",
    "#303F9F",
    "#512DA8",
    "#5E35B1",
    "#7B1FA2",
    "#8E24AA",
    "#AD1457",
    "#C2185B",
    "#D32F2F",
    "#E64A19",
    "#F57C00",
    "#FF8F00",
    "#388E3C",
    "#00695C",
    "#0097A7",
    "#455A64",
    "#546E7A",
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
FONT_BOLD_PATH = DATA_DIR / "font_bold.ttf"
FONT_REGULAR_PATH = DATA_DIR / "font_regular.ttf"
CHANNEL_LOGO_PATH = DATA_DIR / "channel_logo.png"


class BannerConfig(NamedTuple):
    width: int = 1920
    height: int = 1080
    text_color: str = "white"
    margin: int = 100
    footer_margin: int = 50
    footer_text: str = "@AndroidRepo"
    logo_size: int = 100
    footer_font_size: int = 54
    min_font_size: int = 40
    max_font_size: int = 180


CONFIG = BannerConfig()


@contextmanager
def managed_image(*args, **kwargs) -> Generator[Image.Image]:
    img = None
    try:
        img = Image.new(*args, **kwargs)
        yield img
    finally:
        if img:
            img.close()


@lru_cache(maxsize=32)
def hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    hex_color = hex_color.lstrip("#")
    rgb_values = [int(hex_color[i : i + 2], 16) for i in (0, 2, 4)]
    return (rgb_values[0], rgb_values[1], rgb_values[2])


def create_gradient_background(width: int, height: int, base_color: str) -> Image.Image:
    base_rgb = hex_to_rgb(base_color)
    lighter_rgb = tuple(min(255, int(c * 1.3)) for c in base_rgb)
    darker_rgb = tuple(int(c * 0.6) for c in base_rgb)

    gradient = Image.new("RGB", (width, height))
    try:
        pixels = gradient.load()

        if pixels is None:
            return gradient

        for y in range(height):
            ratio = y / height
            if ratio < 0.5:
                factor = ratio * 2
                color = tuple(
                    int(lighter_rgb[i] * (1 - factor) + base_rgb[i] * factor) for i in range(3)
                )
            else:
                factor = (ratio - 0.5) * 2
                color = tuple(
                    int(base_rgb[i] * (1 - factor) + darker_rgb[i] * factor) for i in range(3)
                )

            for x in range(width):
                pixels[x, y] = color

        return gradient
    except Exception:
        gradient.close()
        raise


def add_channel_logo(
    image: Image.Image, logo_path: Path, position: tuple[int, int], size: int = 50
) -> None:
    try:
        with Image.open(logo_path) as logo:
            logo_resized = logo.convert("RGBA").resize((size, size), Image.Resampling.LANCZOS)
            try:
                image.paste(logo_resized, position, logo_resized)
            finally:
                logo_resized.close()
    except (OSError, ValueError, FileNotFoundError):
        pass


@lru_cache(maxsize=8)
def get_font(font_path: Path, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    try:
        return ImageFont.truetype(str(font_path), size)
    except OSError:
        return ImageFont.load_default(size)


def wrap_text(
    text: str, font: ImageFont.FreeTypeFont | ImageFont.ImageFont, max_width: int
) -> list[str]:
    words = text.split()
    if not words:
        return []

    lines = []
    current_line = ""

    for word in words:
        test_line = f"{current_line} {word}" if current_line else word
        text_width = get_text_width(test_line, font)

        if text_width <= max_width:
            current_line = test_line
        elif current_line:
            lines.append(current_line)
            current_line = word
        else:
            lines.append(word)

    if current_line:
        lines.append(current_line)

    return lines


def get_text_width(text: str, font: ImageFont.FreeTypeFont | ImageFont.ImageFont) -> int:
    try:
        return int(font.getbbox(text)[2])
    except (AttributeError, OSError):
        return len(text) * 10


def get_text_dimensions(
    text: str, font: ImageFont.FreeTypeFont | ImageFont.ImageFont
) -> tuple[int, int]:
    try:
        bbox = font.getbbox(text)
        return int(bbox[2] - bbox[0]), int(bbox[3] - bbox[1])
    except (AttributeError, OSError):
        return len(text) * 10, 20


def generate_banner(title_text: str) -> BytesIO:
    config = CONFIG
    bg_color = random.choice(MATERIAL_COLORS)

    image = None
    try:
        image = create_gradient_background(config.width, config.height, bg_color)
        draw = ImageDraw.Draw(image)

        max_title_width = config.width - (2 * config.margin)
        max_title_height = config.height - 400

        title_font_size = config.max_font_size
        title_lines = []

        while title_font_size > config.min_font_size:
            title_font = get_font(FONT_BOLD_PATH, title_font_size)
            title_lines = wrap_text(title_text, title_font, max_title_width)

            if not title_lines:
                break

            total_height = (
                sum(get_text_dimensions(line, title_font)[1] + 10 for line in title_lines) - 10
            )
            max_line_width = max(get_text_dimensions(line, title_font)[0] for line in title_lines)

            if max_line_width <= max_title_width and total_height <= max_title_height:
                break

            title_font_size -= 10

        if not title_lines:
            title_font = get_font(FONT_BOLD_PATH, config.min_font_size)
            title_lines = [title_text]

        line_height = get_text_dimensions("Ag", title_font)[1] + 10
        total_text_height = len(title_lines) * line_height - 10
        start_y = (config.height - total_text_height) / 2 - 30

        for i, line in enumerate(title_lines):
            line_width = get_text_dimensions(line, title_font)[0]
            line_x = (config.width - line_width) / 2
            line_y = start_y + (i * line_height)
            draw.text((line_x, line_y), line, fill=config.text_color, font=title_font)

        footer_font = get_font(FONT_REGULAR_PATH, config.footer_font_size)
        footer_width, footer_height = get_text_dimensions(config.footer_text, footer_font)

        padding = 15
        footer_y = config.height - footer_height - config.footer_margin
        total_footer_width = footer_width + config.logo_size + padding
        footer_x = max(
            config.width - config.footer_margin - total_footer_width, config.footer_margin
        )

        logo_x = footer_x + footer_width + padding
        logo_y = footer_y + (footer_height - config.logo_size) // 2 + 5

        draw.text(
            (footer_x, footer_y), config.footer_text, fill=config.text_color, font=footer_font
        )
        add_channel_logo(image, CHANNEL_LOGO_PATH, (int(logo_x), int(logo_y)), config.logo_size)

        buffer = BytesIO()
        image.save(buffer, format="PNG", optimize=True, quality=95)
        buffer.seek(0)
        return buffer

    finally:
        if image:
            image.close()


@contextmanager
def banner_context(title_text: str, output_filename: str | None = None):
    banner_buffer = None
    try:
        banner_buffer = generate_banner(title_text)
        yield banner_buffer
    finally:
        if banner_buffer:
            banner_buffer.close()


def generate_banner_file(title_text: str, output_filename: str) -> Path:
    config = CONFIG
    bg_color = random.choice(MATERIAL_COLORS)

    image = None
    try:
        image = create_gradient_background(config.width, config.height, bg_color)
        draw = ImageDraw.Draw(image)

        max_title_width = config.width - (2 * config.margin)
        max_title_height = config.height - 400

        title_font_size = config.max_font_size
        title_lines = []

        while title_font_size > config.min_font_size:
            title_font = get_font(FONT_BOLD_PATH, title_font_size)
            title_lines = wrap_text(title_text, title_font, max_title_width)

            if not title_lines:
                break

            total_height = (
                sum(get_text_dimensions(line, title_font)[1] + 10 for line in title_lines) - 10
            )
            max_line_width = max(get_text_dimensions(line, title_font)[0] for line in title_lines)

            if max_line_width <= max_title_width and total_height <= max_title_height:
                break

            title_font_size -= 10

        if not title_lines:
            title_font = get_font(FONT_BOLD_PATH, config.min_font_size)
            title_lines = [title_text]

        line_height = get_text_dimensions("Ag", title_font)[1] + 10
        total_text_height = len(title_lines) * line_height - 10
        start_y = (config.height - total_text_height) / 2 - 30

        for i, line in enumerate(title_lines):
            line_width = get_text_dimensions(line, title_font)[0]
            line_x = (config.width - line_width) / 2
            line_y = start_y + (i * line_height)
            draw.text((line_x, line_y), line, fill=config.text_color, font=title_font)

        footer_font = get_font(FONT_REGULAR_PATH, config.footer_font_size)
        footer_width, footer_height = get_text_dimensions(config.footer_text, footer_font)

        padding = 15
        footer_y = config.height - footer_height - config.footer_margin
        total_footer_width = footer_width + config.logo_size + padding
        footer_x = max(
            config.width - config.footer_margin - total_footer_width, config.footer_margin
        )

        logo_x = footer_x + footer_width + padding
        logo_y = footer_y + (footer_height - config.logo_size) // 2 + 5

        draw.text(
            (footer_x, footer_y), config.footer_text, fill=config.text_color, font=footer_font
        )
        add_channel_logo(image, CHANNEL_LOGO_PATH, (int(logo_x), int(logo_y)), config.logo_size)

        image.save(output_filename, format="PNG", optimize=True, quality=95)

        return Path(output_filename)

    finally:
        if image:
            image.close()
