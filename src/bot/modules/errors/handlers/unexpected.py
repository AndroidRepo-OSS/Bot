# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations

from typing import TYPE_CHECKING

from aiogram import Router

from bot.logging import get_logger

if TYPE_CHECKING:
    from aiogram.types import ErrorEvent

logger = get_logger(__name__)
router = Router(name="errors-unexpected")


@router.error()
async def handle_unexpected_error(event: ErrorEvent) -> bool:
    await logger.aexception(
        "Unexpected error during update processing",
        update_id=event.update.update_id,
        exception=str(event.exception),
        exc_info=event.exception,
    )
    return True
