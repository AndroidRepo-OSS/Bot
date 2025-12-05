# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations

from typing import TYPE_CHECKING

from aiogram import F, Router
from aiogram.filters import ExceptionTypeFilter

from bot.integrations.ai import PreviewEditError, RepositorySummaryError
from bot.integrations.repositories import RepositoryClientError
from bot.logging import get_logger
from bot.modules.post.utils.repositories import RepositoryUrlParseError

if TYPE_CHECKING:
    from aiogram.types import ErrorEvent, Message

logger = get_logger(__name__)
router = Router(name="post-errors")


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
