# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations

from typing import TYPE_CHECKING

from aiogram import Router
from aiogram.utils.callback_answer import CallbackAnswerMiddleware

from bot.filters import ChatFilter, TopicFilter

from .handlers import debug, errors, post_router

if TYPE_CHECKING:
    from aiogram import Dispatcher

router = Router(name="post-module")


def setup_post(dp: Dispatcher, *, allowed_chat_id: int, post_topic_id: int) -> None:
    chat_filter = ChatFilter(allowed_chat_id)
    topic_filter = TopicFilter(post_topic_id)

    post_router.message.filter(chat_filter)
    post_router.callback_query.filter(chat_filter)

    post_router.message.filter(topic_filter)
    post_router.callback_query.filter(topic_filter)

    post_router.callback_query.middleware(CallbackAnswerMiddleware())

    router.include_router(debug.router)
    router.include_router(post_router)
    router.include_router(errors.router)

    dp.include_router(router)


__all__ = ("setup_post",)
