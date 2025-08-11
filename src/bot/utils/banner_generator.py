# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations

import random
from functools import lru_cache
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from pydantic import BaseModel, ConfigDict, Field

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


class BannerConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    width: int = Field(default=1920, gt=0, description="Banner width in pixels")
    height: int = Field(default=1080, gt=0, description="Banner height in pixels")
    text_color: str = Field(default="white", description="Text color for the banner")
    margin: int = Field(default=100, ge=0, description="Banner margin in pixels")
    footer_margin: int = Field(default=50, ge=0, description="Footer margin in pixels")
    footer_text: str = Field(default="@AndroidRepo", description="Footer text to display")
    logo_size: int = Field(default=100, gt=0, description="Logo size in pixels")
    footer_font_size: int = Field(default=54, gt=0, description="Footer font size")
    min_font_size: int = Field(default=40, gt=0, description="Minimum font size for title")
    max_font_size: int = Field(default=180, gt=0, description="Maximum font size for title")


class BannerGenerator:
    def __init__(self, config: BannerConfig | None = None):
        self.config = config or BannerConfig()

    @staticmethod
    @lru_cache(maxsize=32)
    def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
        hex_color = hex_color.lstrip("#")
        r, g, b = (int(hex_color[i : i + 2], 16) for i in (0, 2, 4))
        return (r, g, b)

    def _calculate_gradient_colors(self, base_color: str) -> list[tuple[int, int, int]]:
        base_rgb = self._hex_to_rgb(base_color)
        lighter_rgb = tuple(min(255, int(c * 1.3)) for c in base_rgb)
        darker_rgb = tuple(int(c * 0.6) for c in base_rgb)

        colors = []
        for y in range(self.config.height):
            ratio = y / self.config.height
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
            colors.append(color)
        return colors

    def _create_gradient_background(self, base_color: str) -> Image.Image:
        try:
            column = Image.new("RGB", (1, self.config.height))
            column.putdata(self._calculate_gradient_colors(base_color))
            gradient = column.resize(
                (self.config.width, self.config.height), Image.Resampling.BILINEAR
            )
            column.close()
            return gradient
        except Exception:
            column.close()
            raise

    @staticmethod
    def _add_channel_logo(image: Image.Image, position: tuple[int, int], size: int = 50) -> None:
        try:
            with Image.open(CHANNEL_LOGO_PATH) as logo:
                logo_resized = logo.convert("RGBA").resize((size, size), Image.Resampling.LANCZOS)
                try:
                    image.paste(logo_resized, position, logo_resized)
                finally:
                    logo_resized.close()
        except (OSError, ValueError, FileNotFoundError):
            pass

    @staticmethod
    @lru_cache(maxsize=8)
    def _get_font(font_path: Path, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
        try:
            return ImageFont.truetype(str(font_path), size)
        except OSError:
            return ImageFont.load_default()

    @classmethod
    @lru_cache(maxsize=128)
    def _get_text_dimensions(cls, text: str, font_path: str, font_size: int) -> tuple[int, int]:
        font = cls._get_font(Path(font_path), font_size)
        try:
            bbox = font.getbbox(text)
            return int(bbox[2] - bbox[0]), int(bbox[3] - bbox[1])
        except (AttributeError, OSError):
            return len(text) * 10, 20

    def _wrap_text(self, text: str, max_width: int, font_path: str, font_size: int) -> list[str]:
        words = text.split()
        if not words:
            return []

        lines = []
        current_line = ""

        for word in words:
            test_line = f"{current_line} {word}" if current_line else word
            text_width = self._get_text_dimensions(test_line, font_path, font_size)[0]

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

    def _draw_title_text(self, draw: ImageDraw.ImageDraw, title_text: str) -> None:
        max_title_width = self.config.width - (2 * self.config.margin)
        max_title_height = self.config.height - 400
        font_path_str = str(FONT_BOLD_PATH)

        title_font_size = self.config.max_font_size
        title_lines = []

        while title_font_size > self.config.min_font_size:
            title_lines = self._wrap_text(
                title_text, max_title_width, font_path_str, title_font_size
            )

            if not title_lines:
                break

            total_height = (
                sum(
                    self._get_text_dimensions(line, font_path_str, title_font_size)[1] + 10
                    for line in title_lines
                )
                - 10
            )

            max_line_width = max(
                self._get_text_dimensions(line, font_path_str, title_font_size)[0]
                for line in title_lines
            )

            if max_line_width <= max_title_width and total_height <= max_title_height:
                break
            title_font_size -= 10

        if not title_lines:
            title_lines = [title_text]
            title_font_size = self.config.min_font_size

        title_font = self._get_font(FONT_BOLD_PATH, title_font_size)
        line_height = self._get_text_dimensions("Ag", font_path_str, title_font_size)[1] + 10
        total_text_height = len(title_lines) * line_height - 10
        start_y = (self.config.height - total_text_height) / 2 - 30

        for i, line in enumerate(title_lines):
            line_width = self._get_text_dimensions(line, font_path_str, title_font_size)[0]
            line_x = (self.config.width - line_width) / 2
            line_y = start_y + (i * line_height)
            draw.text((line_x, line_y), line, fill=self.config.text_color, font=title_font)

    def _draw_footer(self, image: Image.Image, draw: ImageDraw.ImageDraw) -> None:
        footer_font = self._get_font(FONT_REGULAR_PATH, self.config.footer_font_size)
        footer_width, footer_height = self._get_text_dimensions(
            self.config.footer_text, str(FONT_REGULAR_PATH), self.config.footer_font_size
        )

        padding = 15
        footer_y = self.config.height - footer_height - self.config.footer_margin
        total_footer_width = footer_width + self.config.logo_size + padding
        footer_x = max(
            self.config.width - self.config.footer_margin - total_footer_width,
            self.config.footer_margin,
        )

        logo_x = footer_x + footer_width + padding
        logo_y = footer_y + (footer_height - self.config.logo_size) // 2 + 5

        draw.text(
            (footer_x, footer_y),
            self.config.footer_text,
            fill=self.config.text_color,
            font=footer_font,
        )
        self._add_channel_logo(image, (int(logo_x), int(logo_y)), self.config.logo_size)

    def generate(self, title_text: str) -> BytesIO:
        bg_color = random.choice(MATERIAL_COLORS)
        image = self._create_gradient_background(bg_color)

        try:
            draw = ImageDraw.Draw(image)
            self._draw_title_text(draw, title_text)
            self._draw_footer(image, draw)

            buffer = BytesIO()
            image.save(buffer, format="PNG", optimize=True, compress_level=9)
            buffer.seek(0)
            return buffer
        finally:
            image.close()


def generate_banner(title_text: str) -> BytesIO:
    generator = BannerGenerator()
    return generator.generate(title_text)
