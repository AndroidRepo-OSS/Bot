# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations

import secrets
from dataclasses import dataclass
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING, Final

from PIL import Image, ImageDraw, ImageFont

if TYPE_CHECKING:
    from collections.abc import Sequence

    type RGBColor = tuple[int, int, int]
    type FontType = ImageFont.FreeTypeFont | ImageFont.ImageFont

MATERIAL_COLORS: Final[tuple[str, ...]] = (
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

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
DATA_DIR: Final[Path] = PROJECT_ROOT / "data"
FONT_BOLD_PATH: Final[Path] = DATA_DIR / "Inter-Bold.ttf"
FONT_REGULAR_PATH: Final[Path] = DATA_DIR / "Inter-Regular.ttf"
CHANNEL_LOGO_PATH: Final[Path] = DATA_DIR / "channel_logo.png"

GRADIENT_MIDPOINT: Final[float] = 0.5
FONT_SIZE_STEP: Final[int] = 10
LINE_HEIGHT_PADDING: Final[int] = 10
TITLE_VERTICAL_OFFSET: Final[int] = 30
FOOTER_PADDING: Final[int] = 15
LOGO_VERTICAL_OFFSET: Final[int] = 5
RESERVED_HEIGHT: Final[int] = 400


@dataclass(frozen=True, slots=True, kw_only=True)
class TextLayout:
    lines: Sequence[tuple[str, int]]
    font: FontType
    line_height: int
    start_y: float


@dataclass(frozen=True, slots=True, kw_only=True)
class BannerConfig:
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


class BannerGenerator:
    __slots__ = ("config",)

    def __init__(self, config: BannerConfig | None = None) -> None:
        self.config = config or BannerConfig()

    @staticmethod
    @lru_cache(maxsize=32)
    def _hex_to_rgb(hex_color: str) -> RGBColor:
        hex_clean = hex_color.lstrip("#")
        return (int(hex_clean[0:2], 16), int(hex_clean[2:4], 16), int(hex_clean[4:6], 16))

    @staticmethod
    def _blend_color(c1: RGBColor, c2: RGBColor, factor: float) -> RGBColor:
        inv_factor = 1 - factor
        return (
            int(c1[0] * inv_factor + c2[0] * factor),
            int(c1[1] * inv_factor + c2[1] * factor),
            int(c1[2] * inv_factor + c2[2] * factor),
        )

    @staticmethod
    @lru_cache(maxsize=64)
    def _calculate_gradient_colors(base_color: str, height: int) -> tuple[RGBColor, ...]:
        base_rgb = BannerGenerator._hex_to_rgb(base_color)
        lighter_rgb: RGBColor = (
            min(255, int(base_rgb[0] * 1.3)),
            min(255, int(base_rgb[1] * 1.3)),
            min(255, int(base_rgb[2] * 1.3)),
        )
        darker_rgb: RGBColor = (int(base_rgb[0] * 0.6), int(base_rgb[1] * 0.6), int(base_rgb[2] * 0.6))

        return tuple(
            BannerGenerator._blend_color(lighter_rgb, base_rgb, (y / height) * 2)
            if (y / height) < GRADIENT_MIDPOINT
            else BannerGenerator._blend_color(base_rgb, darker_rgb, ((y / height) - GRADIENT_MIDPOINT) * 2)
            for y in range(height)
        )

    @classmethod
    @lru_cache(maxsize=len(MATERIAL_COLORS))
    def _create_gradient_background(cls, base_color: str, width: int, height: int) -> Image.Image:
        column = Image.new("RGB", (1, height))
        column.putdata(cls._calculate_gradient_colors(base_color, height))
        return column.resize((width, height), Image.Resampling.BILINEAR)

    @staticmethod
    @lru_cache(maxsize=8)
    def _load_logo(size: int) -> Image.Image | None:
        try:
            with Image.open(CHANNEL_LOGO_PATH) as logo:
                return logo.convert("RGBA").resize((size, size), Image.Resampling.LANCZOS)
        except FileNotFoundError, OSError, ValueError:
            return None

    @classmethod
    def _add_channel_logo(cls, image: Image.Image, position: tuple[int, int], size: int = 50) -> None:
        logo = cls._load_logo(size)
        if logo is not None:
            image.paste(logo, position, logo)

    @staticmethod
    @lru_cache(maxsize=8)
    def _get_font(font_path: Path, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
        try:
            return ImageFont.truetype(str(font_path), size)
        except OSError:
            try:
                return ImageFont.load_default(size)
            except TypeError:
                return ImageFont.load_default()

    @classmethod
    @lru_cache(maxsize=128)
    def _get_text_dimensions(cls, text: str, font_path: Path, font_size: int) -> tuple[int, int]:
        font = cls._get_font(font_path, font_size)
        try:
            bbox = font.getbbox(text)
            return int(bbox[2] - bbox[0]), int(bbox[3] - bbox[1])
        except AttributeError, OSError:
            return len(text) * 10, 20

    @staticmethod
    @lru_cache(maxsize=64)
    def _line_height(font_path: Path, font_size: int) -> int:
        return BannerGenerator._get_text_dimensions("Ag", font_path, font_size)[1] + LINE_HEIGHT_PADDING

    def _wrap_text(self, text: str, max_width: int, font_path: Path, font_size: int) -> list[str]:
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

    def _compute_title_layout(self, title_text: str) -> TextLayout:
        max_title_width = self.config.width - (2 * self.config.margin)
        max_title_height = self.config.height - RESERVED_HEIGHT
        font_path = FONT_BOLD_PATH

        font_size = self.config.max_font_size
        selected_lines: list[str] = []
        measured_lines: list[tuple[str, int]] = []

        while font_size > self.config.min_font_size:
            candidate_lines = self._wrap_text(title_text, max_title_width, font_path, font_size)
            if not candidate_lines:
                break

            line_height = self._line_height(font_path, font_size)
            total_height = len(candidate_lines) * line_height - LINE_HEIGHT_PADDING

            widths = [self._get_text_dimensions(line, font_path, font_size)[0] for line in candidate_lines]
            max_line_width = max(widths)

            if max_line_width <= max_title_width and total_height <= max_title_height:
                selected_lines = candidate_lines
                measured_lines = list(zip(candidate_lines, widths, strict=True))
                break
            font_size -= FONT_SIZE_STEP

        if not selected_lines:
            font_size = self.config.min_font_size
            selected_lines = [title_text]
            fallback_width = self._get_text_dimensions(title_text, font_path, font_size)[0]
            measured_lines = [(title_text, fallback_width)]

        line_height = self._line_height(font_path, font_size)
        total_text_height = len(selected_lines) * line_height - LINE_HEIGHT_PADDING
        start_y = (self.config.height - total_text_height) / 2 - TITLE_VERTICAL_OFFSET
        font = self._get_font(font_path, font_size)

        return TextLayout(lines=measured_lines, font=font, line_height=line_height, start_y=start_y)

    def _draw_title_text(self, draw: ImageDraw.ImageDraw, title_text: str) -> None:
        layout = self._compute_title_layout(title_text)

        for index, (line, width) in enumerate(layout.lines):
            line_x = (self.config.width - width) / 2
            line_y = layout.start_y + (index * layout.line_height)
            draw.text((line_x, line_y), line, fill=self.config.text_color, font=layout.font)

    def _draw_footer(self, image: Image.Image, draw: ImageDraw.ImageDraw) -> None:
        footer_font = self._get_font(FONT_REGULAR_PATH, self.config.footer_font_size)
        footer_width, footer_height = self._get_text_dimensions(
            self.config.footer_text, FONT_REGULAR_PATH, self.config.footer_font_size
        )

        footer_y = self.config.height - footer_height - self.config.footer_margin
        total_footer_width = footer_width + self.config.logo_size + FOOTER_PADDING
        footer_x = max(self.config.width - self.config.footer_margin - total_footer_width, self.config.footer_margin)

        logo_x = footer_x + footer_width + FOOTER_PADDING
        logo_y = footer_y + (footer_height - self.config.logo_size) // 2 + LOGO_VERTICAL_OFFSET

        draw.text((footer_x, footer_y), self.config.footer_text, fill=self.config.text_color, font=footer_font)
        self._add_channel_logo(image, (int(logo_x), int(logo_y)), self.config.logo_size)

    def generate(self, title_text: str) -> bytes:
        bg_color = secrets.choice(MATERIAL_COLORS)
        image = self._create_gradient_background(bg_color, self.config.width, self.config.height).copy()

        try:
            draw = ImageDraw.Draw(image)
            self._draw_title_text(draw, title_text)
            self._draw_footer(image, draw)

            buffer = BytesIO()
            image.save(buffer, format="PNG", optimize=True, compress_level=9)
            return buffer.getvalue()
        finally:
            image.close()
