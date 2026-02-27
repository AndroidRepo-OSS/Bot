# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations

from aiogram import F, Router
from aiogram.utils.callback_answer import CallbackAnswerMiddleware

from .handlers import command, debug, edit, publish

_INTERACTIVE_ROUTERS = (command.router, edit.router, publish.router)


def create_post_router(*, allowed_chat_id: int, post_topic_id: int) -> Router:
    router = Router(name="post")

    for child_router in _INTERACTIVE_ROUTERS:
        _configure_post_interactions(child_router, allowed_chat_id=allowed_chat_id, post_topic_id=post_topic_id)

    router.include_routers(*_INTERACTIVE_ROUTERS, debug.router)
    return router


def _configure_post_interactions(router: Router, *, allowed_chat_id: int, post_topic_id: int) -> None:
    router.message.filter(F.chat.id == allowed_chat_id, F.message_thread_id == post_topic_id)
    router.callback_query.filter(F.message.chat.id == allowed_chat_id, F.message.message_thread_id == post_topic_id)
    router.callback_query.middleware(CallbackAnswerMiddleware())


__all__ = ("create_post_router",)
