# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations

import base64
from contextlib import suppress
from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import uuid4

from aiogram import F, Router, flags
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, InputMediaPhoto, Message
from aiogram.utils.deep_linking import create_start_link
from aiogram.utils.keyboard import InlineKeyboardBuilder
from anyio import create_task_group, to_thread
from pydantic import BaseModel, ConfigDict

from bot.integrations import RepositorySummary
from bot.utils.deeplinks import build_preview_payload
from bot.utils.messages import render_post_caption
from bot.utils.repositories import parse_repository_url, select_fetcher

if TYPE_CHECKING:
    from aiogram import Bot
    from aiogram.filters import CommandObject
    from aiogram.fsm.context import FSMContext
    from aiogram.types import CallbackQuery

    from bot.container import BotDependencies
    from bot.integrations.repositories import RepositoryInfo
    from bot.services import BannerGenerator, PreviewDebugRegistry

    type MessageRef = tuple[int, int]

router = Router(name="post")


class SubmissionAction(StrEnum):
    PUBLISH = "publish"
    EDIT = "edit"
    CANCEL = "cancel"


class PostStates(StatesGroup):
    waiting_for_url = State()
    waiting_for_confirmation = State()
    waiting_for_edit_instructions = State()


class SubmissionCallback(CallbackData, prefix="post"):
    action: SubmissionAction
    submission_id: str


class SubmissionData(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    submission_id: str
    caption: str
    banner_b64: str
    preview_chat_id: int
    preview_message_id: int
    original_chat_id: int
    original_message_id: int

    prompt_chat_id: int | None = None
    prompt_message_id: int | None = None
    command_chat_id: int | None = None
    command_message_id: int | None = None

    edit_prompt_chat_id: int | None = None
    edit_prompt_message_id: int | None = None
    edit_request_chat_id: int | None = None
    edit_request_message_id: int | None = None
    edit_status_chat_id: int | None = None
    edit_status_message_id: int | None = None

    summary: dict[str, object] | None = None
    debug_url: str | None = None

    @classmethod
    def from_state(cls, data: dict[str, object]) -> SubmissionData | None:
        with suppress(Exception):
            return cls.model_validate(data)
        return None

    @property
    def banner_bytes(self) -> bytes | None:
        with suppress(ValueError):
            return base64.b64decode(self.banner_b64, validate=True)
        return None

    @property
    def repository_summary(self) -> RepositorySummary | None:
        if self.summary is None:
            return None
        with suppress(Exception):
            return RepositorySummary.model_validate(self.summary)
        return None

    @property
    def cleanup_targets(self) -> list[MessageRef]:
        pairs = (
            (self.original_chat_id, self.original_message_id),
            (self.prompt_chat_id, self.prompt_message_id),
            (self.command_chat_id, self.command_message_id),
            (self.edit_prompt_chat_id, self.edit_prompt_message_id),
            (self.edit_request_chat_id, self.edit_request_message_id),
            (self.edit_status_chat_id, self.edit_status_message_id),
        )
        return [(c, m) for c, m in pairs if c and m]


@router.message(Command("post"))
async def handle_post_command(
    message: Message, command: CommandObject, state: FSMContext, bot_dependencies: BotDependencies
) -> None:
    await _reset_submission_state(state, bot_dependencies.preview_registry)

    await state.update_data(command_chat_id=message.chat.id, command_message_id=message.message_id)

    if args := (command.args or "").strip():
        await _process_repository(message, args, state, bot_dependencies)
        return

    await state.set_state(PostStates.waiting_for_url)
    prompt = await message.answer("Send the GitHub or GitLab repository URL you want to share.")
    await state.update_data(prompt_chat_id=prompt.chat.id, prompt_message_id=prompt.message_id)


@router.message(PostStates.waiting_for_url)
async def handle_repository_input(message: Message, state: FSMContext, bot_dependencies: BotDependencies) -> None:
    if not message.text:
        await message.answer("Please send the repository URL as plain text.")
        return
    await _process_repository(message, message.text, state, bot_dependencies)


@router.callback_query(SubmissionCallback.filter(F.action == SubmissionAction.PUBLISH))
@flags.callback_answer(text="Published in @AndroidRepo!")
async def handle_publish_callback(
    callback: CallbackQuery,
    callback_data: SubmissionCallback,
    state: FSMContext,
    bot: Bot,
    bot_dependencies: BotDependencies,
) -> None:
    submission = await _validate_submission(callback, callback_data, state)
    if not submission:
        return

    if not (banner_bytes := submission.banner_bytes):
        await callback.answer("Preview data is corrupted. Please start over.", show_alert=True)
        await _reset_submission_state(state, bot_dependencies.preview_registry)
        return

    photo = BufferedInputFile(banner_bytes, filename=f"post-{submission.submission_id}.png")
    await bot.send_photo(chat_id=bot_dependencies.settings.post_channel_id, photo=photo, caption=submission.caption)

    preview_message = callback.message if isinstance(callback.message, Message) else None
    await _cleanup_submission_messages(bot, submission, preview_message)
    bot_dependencies.preview_registry.discard(submission.submission_id)
    await state.clear()


@router.callback_query(SubmissionCallback.filter(F.action == SubmissionAction.CANCEL))
@flags.callback_answer(text="Preview cancelled.")
async def handle_cancel_callback(
    callback: CallbackQuery,
    callback_data: SubmissionCallback,
    state: FSMContext,
    bot: Bot,
    bot_dependencies: BotDependencies,
) -> None:
    submission = await _validate_submission(callback, callback_data, state)
    if not submission:
        return

    preview_message = callback.message if isinstance(callback.message, Message) else None
    await _cleanup_submission_messages(bot, submission, preview_message)
    bot_dependencies.preview_registry.discard(submission.submission_id)
    await state.clear()


@router.callback_query(SubmissionCallback.filter(F.action == SubmissionAction.EDIT))
@flags.callback_answer(text="Got it! Waiting for your edit request.")
async def handle_edit_callback(
    callback: CallbackQuery,
    callback_data: SubmissionCallback,
    state: FSMContext,
    bot: Bot,
    bot_dependencies: BotDependencies,
) -> None:
    submission = await _validate_submission(callback, callback_data, state)
    if not submission:
        return

    if not bot_dependencies.preview_registry.get(submission.submission_id):
        await callback.answer("Repository context is missing. Please restart /post.", show_alert=True)
        await state.clear()
        return

    if not isinstance(callback.message, Message):
        return

    prompt = await callback.message.answer(
        "Send a message explaining how the preview should change. "
        "You can mention tone tweaks, features to highlight, or text to remove."
    )

    await _track_message(state, bot, prompt, "edit_prompt", submission)
    await state.set_state(PostStates.waiting_for_edit_instructions)


@router.message(PostStates.waiting_for_edit_instructions)
async def handle_edit_instructions(
    message: Message, state: FSMContext, bot_dependencies: BotDependencies, bot: Bot
) -> None:
    text = (message.text or "").strip()
    if not text:
        await message.answer("Please describe the desired edits using plain text.")
        return

    submission = SubmissionData.from_state(await state.get_data())
    if not submission:
        await message.answer("This preview expired. Please run /post again.")
        await state.clear()
        return

    repository = bot_dependencies.preview_registry.get(submission.submission_id)
    summary = submission.repository_summary

    if not repository or not summary:
        await message.answer("Session data is unavailable. Please restart /post.")
        await state.clear()
        return

    await _track_message(state, bot, message, "edit_request", submission)
    await _try_delete(bot, submission.edit_prompt_chat_id, submission.edit_prompt_message_id)

    progress = await message.answer("[1/3] Understanding your edit request...")
    await _track_message(state, bot, progress, "edit_status", submission)

    updated_summary = await bot_dependencies.revision_agent.revise(
        repository=repository, summary=summary, edit_request=text
    )

    await _update_progress(progress, "[2/3] Updating banner...")
    banner_bytes = await _render_banner(bot_dependencies.banner_generator, repository, updated_summary)

    await _update_progress(progress, "[3/3] Updating preview message...")
    caption = render_post_caption(repository, updated_summary)

    await _update_preview_message(bot, submission, banner_bytes, caption, repository.name)

    await state.update_data(
        caption=caption,
        banner_b64=base64.b64encode(banner_bytes).decode("ascii"),
        summary=updated_summary.model_dump(mode="json"),
        edit_prompt_chat_id=None,
        edit_prompt_message_id=None,
    )
    await state.set_state(PostStates.waiting_for_confirmation)
    await _update_progress(progress, "Preview updated! You can publish, edit again, or cancel.")


async def _process_repository(
    message: Message, raw_url: str, state: FSMContext, bot_dependencies: BotDependencies
) -> None:
    locator = parse_repository_url(raw_url)

    progress = await message.answer("[1/3] Fetching repository metadata...")

    fetcher = select_fetcher(
        locator, github_fetcher=bot_dependencies.github_fetcher, gitlab_fetcher=bot_dependencies.gitlab_fetcher
    )
    repository = await fetcher.fetch_repository(locator.owner, locator.name)

    await _update_progress(progress, "[2/3] Generating AI summary...")
    summary = await bot_dependencies.summary_agent.summarize(repository)

    await _update_progress(progress, "[3/3] Rendering preview...")
    banner_bytes = await _render_banner(bot_dependencies.banner_generator, repository, summary)

    caption = render_post_caption(repository, summary)
    submission_id = uuid4().hex
    bot_dependencies.preview_registry.save(submission_id, repository)

    debug_url = await _build_debug_link(message.bot, submission_id)
    keyboard = _build_preview_keyboard(submission_id, debug_url)

    preview = await message.answer_photo(
        photo=BufferedInputFile(banner_bytes, filename=f"{repository.name}.png"),
        caption=caption,
        reply_markup=keyboard.as_markup(),
    )

    await state.set_state(PostStates.waiting_for_confirmation)
    await state.update_data(
        submission_id=submission_id,
        caption=caption,
        banner_b64=base64.b64encode(banner_bytes).decode("ascii"),
        preview_chat_id=preview.chat.id,
        preview_message_id=preview.message_id,
        original_chat_id=message.chat.id,
        original_message_id=message.message_id,
        summary=summary.model_dump(mode="json"),
        debug_url=debug_url,
    )

    await _delete_message(progress)


async def _validate_submission(
    callback: CallbackQuery, callback_data: SubmissionCallback, state: FSMContext
) -> SubmissionData | None:
    if (submission := SubmissionData.from_state(await state.get_data())) and (
        submission.submission_id == callback_data.submission_id
    ):
        return submission

    await callback.answer("This preview expired. Please run /post again.", show_alert=True)
    return None


async def _reset_submission_state(state: FSMContext, registry: PreviewDebugRegistry) -> None:
    data = await state.get_data()
    if submission := SubmissionData.from_state(data):
        registry.discard(submission.submission_id)
    await state.clear()


async def _render_banner(generator: BannerGenerator, repository: RepositoryInfo, summary: RepositorySummary) -> bytes:
    def _generate() -> bytes:
        with generator.generate(summary.project_name or repository.name) as buffer:
            return buffer.getvalue()

    return await to_thread.run_sync(_generate)


async def _update_preview_message(
    bot: Bot, submission: SubmissionData, banner_bytes: bytes, caption: str, filename: str
) -> None:
    photo = BufferedInputFile(banner_bytes, filename=f"{filename}.png")
    media = InputMediaPhoto(media=photo, caption=caption)
    keyboard = _build_preview_keyboard(submission.submission_id, submission.debug_url)

    await bot.edit_message_media(
        chat_id=submission.preview_chat_id,
        message_id=submission.preview_message_id,
        media=media,
        reply_markup=keyboard.as_markup(),
    )


async def _build_debug_link(bot: Bot | None, submission_id: str) -> str | None:
    if not bot:
        return None
    with suppress(TelegramBadRequest):
        return await create_start_link(bot, build_preview_payload(submission_id), encode=True)
    return None


def _build_preview_keyboard(submission_id: str, debug_url: str | None) -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()

    for text, action in (
        ("Publish", SubmissionAction.PUBLISH),
        ("Edit", SubmissionAction.EDIT),
        ("Cancel", SubmissionAction.CANCEL),
    ):
        builder.button(text=text, callback_data=SubmissionCallback(action=action, submission_id=submission_id))

    if debug_url:
        builder.button(text="Inspect Data", url=debug_url)
        rows = (2, 1, 1)
    else:
        rows = (2, 1)

    builder.adjust(*rows)
    return builder


async def _track_message(
    state: FSMContext, bot: Bot, message: Message, prefix: str, submission: SubmissionData
) -> None:
    if (old_chat := getattr(submission, f"{prefix}_chat_id", None)) and (
        old_msg := getattr(submission, f"{prefix}_message_id", None)
    ):
        await _try_delete(bot, old_chat, old_msg)

    await state.update_data({f"{prefix}_chat_id": message.chat.id, f"{prefix}_message_id": message.message_id})


async def _try_delete(bot: Bot, chat_id: int | None, message_id: int | None) -> None:
    if not chat_id or not message_id:
        return
    with suppress(TelegramBadRequest):
        await bot.delete_message(chat_id=chat_id, message_id=message_id)


async def _update_progress(message: Message, text: str) -> None:
    with suppress(TelegramBadRequest):
        await message.edit_text(text)


async def _delete_message(message: Message | None) -> None:
    if not message:
        return
    with suppress(TelegramBadRequest):
        await message.delete()


async def _cleanup_submission_messages(bot: Bot, submission: SubmissionData, preview_message: Message | None) -> None:
    if not preview_message and not submission.cleanup_targets:
        return

    async with create_task_group() as tg:
        if preview_message:
            tg.start_soon(_delete_message, preview_message)

        for chat_id, message_id in submission.cleanup_targets:
            tg.start_soon(_try_delete, bot, chat_id, message_id)
