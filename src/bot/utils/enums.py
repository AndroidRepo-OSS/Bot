# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from enum import Enum
from urllib.parse import urlparse


class KeyboardType(Enum):
    CONFIRMATION = "confirmation"
    PREVIEW = "preview"


class PostAction(Enum):
    CONFIRM = "confirm"
    CANCEL = "cancel"
    PUBLISH = "publish"
    REGENERATE = "regenerate"


class Platform(Enum):
    GITHUB = "github.com"
    GITLAB = "gitlab.com"

    @classmethod
    def from_url(cls, url: str) -> "Platform":
        netloc = urlparse(url.strip()).netloc
        for platform in cls:
            if netloc == platform.value:
                return platform

        msg = f"Unsupported platform: {netloc}"
        raise ValueError(msg)
