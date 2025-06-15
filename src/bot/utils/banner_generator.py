# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

MATERIAL_COLORS = [
    "#1565C0",  # Blue 800
    "#0D47A1",  # Blue 900
    "#1976D2",  # Blue 700
    "#283593",  # Indigo 700
    "#303F9F",  # Indigo 600
    "#512DA8",  # Deep Purple 700
    "#5E35B1",  # Deep Purple 600
    "#7B1FA2",  # Purple 700
    "#8E24AA",  # Purple 600
    "#AD1457",  # Pink 700
    "#C2185B",  # Pink 600
    "#D32F2F",  # Red 700
    "#E64A19",  # Deep Orange 700
    "#F57C00",  # Orange 700
    "#FF8F00",  # Amber 700
    "#388E3C",  # Green 700
    "#00695C",  # Teal 700
    "#0097A7",  # Cyan 700
    "#455A64",  # Blue Grey 700
    "#546E7A",  # Blue Grey 600
]

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
FONT_BOLD_PATH = str(DATA_DIR / "font_bold.ttf")
FONT_REGULAR_PATH = str(DATA_DIR / "font_regular.ttf")
CHANNEL_LOGO = str(DATA_DIR / "channel_logo.png")

IMAGE_WIDTH = 1920
IMAGE_HEIGHT = 1080
TEXT_COLOR = "white"


def hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    hex_color = hex_color.lstrip("#")
    rgb_values = tuple(int(hex_color[i : i + 2], 16) for i in (0, 2, 4))
    return (rgb_values[0], rgb_values[1], rgb_values[2])


def create_gradient_background(width: int, height: int, base_color: str) -> Image.Image:
    image = Image.new("RGB", (width, height))

    base_rgb = hex_to_rgb(base_color)

    lighter_rgb = tuple(min(255, int(c * 1.3)) for c in base_rgb)
    darker_rgb = tuple(int(c * 0.6) for c in base_rgb)

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
            image.putpixel((x, y), color)

    return image


def add_channel_logo(
    image: Image.Image, logo_path: str, position: tuple[int, int], size: int = 50
) -> None:
    try:
        logo = Image.open(logo_path)

        logo = logo.convert("RGBA")

        logo = logo.resize((size, size), Image.Resampling.LANCZOS)

        image.paste(logo, position, logo)
    except (OSError, ValueError):
        pass


def get_font(font_path: str, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    try:
        return ImageFont.truetype(font_path, size)
    except OSError:
        return ImageFont.load_default()


def wrap_text(
    text: str, font: ImageFont.FreeTypeFont | ImageFont.ImageFont, max_width: int
) -> list[str]:
    words = text.split()
    lines = []
    current_line = ""

    for word in words:
        test_line = current_line + (" " if current_line else "") + word
        try:
            bbox = font.getbbox(test_line)
            text_width = bbox[2] - bbox[0]
        except AttributeError:
            text_width = len(test_line) * 10

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


def get_text_dimensions(
    text: str, font: ImageFont.FreeTypeFont | ImageFont.ImageFont
) -> tuple[int, int]:
    try:
        bbox = font.getbbox(text)
        return int(bbox[2] - bbox[0]), int(bbox[3] - bbox[1])
    except AttributeError:
        return len(text) * 10, 20


def generate_banner(title_text: str, output_filename: str) -> Path:
    bg_color = random.choice(MATERIAL_COLORS)

    image = create_gradient_background(IMAGE_WIDTH, IMAGE_HEIGHT, bg_color)
    draw = ImageDraw.Draw(image)

    margin = 100
    max_title_width = IMAGE_WIDTH - (2 * margin)
    max_title_height = IMAGE_HEIGHT - 400

    title_font_size = 180
    title_font = get_font(FONT_BOLD_PATH, title_font_size)

    while title_font_size > 40:
        title_font = get_font(FONT_BOLD_PATH, title_font_size)
        title_lines = wrap_text(title_text, title_font, max_title_width)

        total_height = 0
        max_line_width = 0

        for line in title_lines:
            line_width, line_height = get_text_dimensions(line, title_font)
            max_line_width = max(max_line_width, line_width)
            total_height += line_height + 10

        if max_line_width <= max_title_width and total_height <= max_title_height:
            break

        title_font_size -= 10

    line_height = get_text_dimensions("Ag", title_font)[1] + 10
    total_text_height = len(title_lines) * line_height - 10

    start_y = (IMAGE_HEIGHT - total_text_height) / 2 - 30

    for i, line in enumerate(title_lines):
        line_width = get_text_dimensions(line, title_font)[0]
        line_x = (IMAGE_WIDTH - line_width) / 2
        line_y = start_y + (i * line_height)
        draw.text((line_x, line_y), line, fill=TEXT_COLOR, font=title_font)

    footer_font_size = 54
    footer_font = get_font(FONT_REGULAR_PATH, footer_font_size)
    footer_text = "@AndroidRepo"

    footer_width, footer_height = get_text_dimensions(footer_text, footer_font)

    footer_margin = 50
    padding = 15
    logo_size = 100

    footer_y = IMAGE_HEIGHT - footer_height - footer_margin

    footer_x = IMAGE_WIDTH - footer_margin - footer_width - logo_size - padding

    if footer_x < footer_margin:
        footer_x = footer_margin
        logo_x = footer_x + footer_width + padding
    else:
        logo_x = footer_x + footer_width + padding

    logo_y = footer_y + (footer_height - logo_size) // 2 + 5

    draw.text((footer_x, footer_y), footer_text, fill=TEXT_COLOR, font=footer_font)
    add_channel_logo(image, CHANNEL_LOGO, (int(logo_x), int(logo_y)), logo_size)

    output_dir = DATA_DIR / "generated_banners"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / output_filename

    image.save(output_path)
    return output_path
