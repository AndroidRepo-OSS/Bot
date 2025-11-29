# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations

from typing import TYPE_CHECKING

from aiogram import F, Router
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramNotFound,
    TelegramRetryAfter,
    TelegramServerError,
)
from aiogram.filters import ExceptionTypeFilter

from bot.integrations import PreviewEditError, RepositoryClientError, RepositorySummaryError
from bot.logging import get_logger
from bot.utils.repositories import RepositoryUrlParseError

if TYPE_CHECKING:
    from aiogram.types import ErrorEvent, Message

logger = get_logger(__name__)
router = Router(name="errors")


@router.error(ExceptionTypeFilter(RepositoryUrlParseError), F.update.message.as_("message"))
async def handle_repository_url_parse_error(event: ErrorEvent, message: Message) -> bool:
    exc = event.exception
    await logger.awarning("Invalid repository URL", error=str(exc))
    await message.answer(str(exc))
    return True


@router.error(ExceptionTypeFilter(RepositoryClientError), F.update.message.as_("message"))
async def handle_repository_client_error(event: ErrorEvent, message: Message) -> bool:
    exc = event.exception
    if isinstance(exc, RepositoryClientError):
        await logger.awarning("Repository client error", platform=exc.platform, status=exc.status, details=exc.details)
    await message.answer("Unable to load repository. Please check the URL and try again.")
    return True


@router.error(ExceptionTypeFilter(RepositorySummaryError), F.update.message.as_("message"))
async def handle_repository_summary_error(event: ErrorEvent, message: Message) -> bool:
    exc = event.exception
    if isinstance(exc, RepositorySummaryError):
        await logger.awarning("Summary generation failed", original_error=str(exc.original_error))
    await message.answer("Could not generate summary. Please try again later.")
    return True


@router.error(ExceptionTypeFilter(PreviewEditError), F.update.message.as_("message"))
async def handle_preview_edit_error(event: ErrorEvent, message: Message) -> bool:
    exc = event.exception
    if isinstance(exc, PreviewEditError):
        await logger.awarning("Preview edit failed", original_error=str(exc.original_error))
    await message.answer("I couldn't apply that edit. Please try rephrasing your request.")
    return True


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


@router.error()
async def handle_unexpected_error(event: ErrorEvent) -> bool:
    await logger.aexception(
        "Unexpected error during update processing",
        update_id=event.update.update_id,
        exception=str(event.exception),
        exc_info=event.exception,
    )
    return True
