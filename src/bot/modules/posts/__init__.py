# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from aiogram import Router

from bot.filters import SudoersFilter

from .handlers import (
    back_to_preview_router,
    cancel_command_router,
    confirm_post_router,
    edit_field_router,
    edit_input_router,
    edit_post_router,
    invalid_url_router,
    post_command_router,
    publish_router,
    regenerate_router,
    repository_url_router,
    scheduled_router,
)

router = Router(name="posts")
router.message.filter(SudoersFilter())
router.callback_query.filter(SudoersFilter())

router.include_routers(
    post_command_router,
    cancel_command_router,
    repository_url_router,
    invalid_url_router,
    edit_input_router,
    confirm_post_router,
    publish_router,
    edit_post_router,
    regenerate_router,
    back_to_preview_router,
    edit_field_router,
    scheduled_router,
)
