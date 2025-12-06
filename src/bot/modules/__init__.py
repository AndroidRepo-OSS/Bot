# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations

from typing import TYPE_CHECKING

from .post import setup_post

if TYPE_CHECKING:
    from aiogram import Dispatcher


def register_modules(dp: Dispatcher, *, allowed_chat_id: int, post_topic_id: int) -> None:
    setup_post(dp, allowed_chat_id=allowed_chat_id, post_topic_id=post_topic_id)


__all__ = ("register_modules",)
