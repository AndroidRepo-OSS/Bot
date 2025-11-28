# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations

from typing import TYPE_CHECKING

from aiogram.utils.callback_answer import CallbackAnswerMiddleware

from bot.filters import ChatFilter, TopicFilter

from . import debug, post, start

if TYPE_CHECKING:
    from aiogram import Dispatcher


def register_all(dp: Dispatcher, *, allowed_chat_id: int, post_topic_id: int) -> None:
    chat_filter = ChatFilter(allowed_chat_id)
    start.router.message.filter(chat_filter)
    post.router.message.filter(chat_filter)
    post.router.callback_query.filter(chat_filter)

    topic_filter = TopicFilter(post_topic_id)
    post.router.message.filter(topic_filter)
    post.router.callback_query.filter(topic_filter)

    callback_answer_middleware = CallbackAnswerMiddleware()
    post.router.callback_query.middleware(callback_answer_middleware)

    dp.include_router(debug.router)
    dp.include_router(start.router)
    dp.include_router(post.router)


__all__ = ("register_all",)
