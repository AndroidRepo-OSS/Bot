# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations

from typing import TYPE_CHECKING

from aiogram import Router
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramNotFound,
    TelegramRetryAfter,
    TelegramServerError,
)
from aiogram.filters import ExceptionTypeFilter

from bot.logging import get_logger

if TYPE_CHECKING:
    from aiogram.types import ErrorEvent

logger = get_logger(__name__)
router = Router(name="errors-telegram")


@router.error(ExceptionTypeFilter(TelegramRetryAfter))
async def handle_telegram_retry_after(event: ErrorEvent) -> bool:
    exc = event.exception
    if isinstance(exc, TelegramRetryAfter):
        await logger.awarning("Telegram rate limit hit", retry_after=exc.retry_after)
    return True


@router.error(ExceptionTypeFilter(TelegramForbiddenError))
async def handle_telegram_forbidden_error(event: ErrorEvent) -> bool:
    await logger.awarning("Telegram forbidden error", exception=str(event.exception))
    return True


@router.error(ExceptionTypeFilter(TelegramNotFound))
async def handle_telegram_not_found_error(event: ErrorEvent) -> bool:
    await logger.adebug("Telegram entity not found", exception=str(event.exception))
    return True


@router.error(ExceptionTypeFilter(TelegramBadRequest))
async def handle_telegram_bad_request(event: ErrorEvent) -> bool:
    await logger.awarning("Telegram bad request", exception=str(event.exception))
    return True


@router.error(ExceptionTypeFilter(TelegramNetworkError))
async def handle_telegram_network_error(event: ErrorEvent) -> bool:
    await logger.aerror("Telegram network error", exception=str(event.exception))
    return True


@router.error(ExceptionTypeFilter(TelegramServerError))
async def handle_telegram_server_error(event: ErrorEvent) -> bool:
    await logger.aerror("Telegram server error", exception=str(event.exception))
    return True
