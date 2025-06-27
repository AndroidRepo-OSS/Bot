# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from enum import Enum
from urllib.parse import urlparse

from aiogram.filters.callback_data import CallbackData


class KeyboardType(Enum):
    CONFIRMATION = "confirmation"
    PREVIEW = "preview"
    EDIT = "edit"
    BACK_TO_EDIT = "back_to_edit"


class PostAction(Enum):
    CONFIRM = "confirm"
    CANCEL = "cancel"
    PUBLISH = "publish"
    EDIT = "edit"
    REGENERATE = "regenerate"
    BACK_TO_PREVIEW = "back_to_preview"


class EditField(Enum):
    DESCRIPTION = "description"
    TAGS = "tags"
    FEATURES = "features"
    LINKS = "links"


class EditAction(Enum):
    FIELD = "field"
    BACK_TO_MENU = "back_to_menu"


class PostCallback(CallbackData, prefix="post"):
    action: PostAction


class EditCallback(CallbackData, prefix="edit"):
    action: EditAction
    field: EditField | None = None


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
