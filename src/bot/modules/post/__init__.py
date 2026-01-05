# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations

from typing import TYPE_CHECKING

from aiogram.utils.callback_answer import CallbackAnswerMiddleware

from bot.filters import ChatFilter, TopicFilter

from .handlers import command, debug, edit, publish

if TYPE_CHECKING:
    from aiogram import Dispatcher


def setup_post(dp: Dispatcher, *, allowed_chat_id: int, post_topic_id: int) -> None:
    chat_filter = ChatFilter(allowed_chat_id)
    topic_filter = TopicFilter(post_topic_id)

    for router in (command.router, edit.router, publish.router):
        router.message.filter(chat_filter, topic_filter)
        router.callback_query.filter(chat_filter, topic_filter)
        router.callback_query.middleware(CallbackAnswerMiddleware())
        dp.include_router(router)

    dp.include_router(debug.router)


__all__ = ("setup_post",)
