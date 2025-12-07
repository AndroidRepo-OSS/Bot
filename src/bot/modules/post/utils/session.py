# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations

from contextlib import suppress
from typing import TYPE_CHECKING

from aiogram.exceptions import TelegramBadRequest
from anyio import create_task_group, sleep

from bot.modules.post.utils.models import SubmissionData

if TYPE_CHECKING:
    from collections.abc import Iterable

    from aiogram import Bot
    from aiogram.fsm.context import FSMContext
    from aiogram.types import CallbackQuery, Message

    from bot.modules.post.utils.models import SubmissionCallback
    from bot.services import PreviewDebugRegistry


async def validate_submission(
    callback: CallbackQuery, callback_data: SubmissionCallback, state: FSMContext
) -> SubmissionData | None:
    submission = await load_submission(state)
    if submission and submission.submission_id == callback_data.submission_id:
        return submission

    await callback.answer("This preview expired. Please run /post again.", show_alert=True)
    return None


async def reset_submission_state(state: FSMContext, registry: PreviewDebugRegistry) -> None:
    submission = await load_submission(state)
    if submission:
        registry.discard(submission.submission_id)

    await state.clear()


async def safe_delete(bot: Bot | None, chat_id: int | None, message_id: int | None) -> None:
    if not bot or not chat_id or not message_id:
        return

    with suppress(TelegramBadRequest):
        await bot.delete_message(chat_id=chat_id, message_id=message_id)


async def cleanup_messages(
    bot: Bot | None, targets: Iterable[tuple[int | None, int | None]], *, delay: float | None = None
) -> None:
    valid_targets = [(chat_id, message_id) for chat_id, message_id in targets if chat_id and message_id]
    if not valid_targets:
        return

    if delay:
        await sleep(delay)

    if len(valid_targets) == 1:
        chat_id, message_id = valid_targets[0]
        await safe_delete(bot, chat_id, message_id)
        return

    async with create_task_group() as tg:
        for chat_id, message_id in valid_targets:
            tg.start_soon(safe_delete, bot, chat_id, message_id)


async def update_progress(message: Message, text: str) -> None:
    with suppress(TelegramBadRequest):
        await message.edit_text(text)


async def load_submission(state: FSMContext) -> SubmissionData | None:
    return SubmissionData.from_state(await state.get_data())
