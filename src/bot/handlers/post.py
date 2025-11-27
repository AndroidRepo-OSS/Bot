# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations

import base64
import binascii
from contextlib import suppress
from enum import StrEnum
from typing import TYPE_CHECKING, Self
from uuid import uuid4

from aiogram import F, Router, flags
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, InputMediaPhoto, Message
from aiogram.utils.deep_linking import create_start_link
from aiogram.utils.keyboard import InlineKeyboardBuilder
from anyio import to_thread
from pydantic import BaseModel, ConfigDict, ValidationError

from bot.integrations import PreviewEditError, RepositoryClientError, RepositorySummary, RepositorySummaryError
from bot.logging import get_logger
from bot.utils.deeplinks import build_preview_payload
from bot.utils.messages import render_post_caption
from bot.utils.repositories import RepositoryUrlParseError, parse_repository_url, select_fetcher

if TYPE_CHECKING:
    from aiogram import Bot
    from aiogram.filters.command import CommandObject
    from aiogram.fsm.context import FSMContext
    from aiogram.types import CallbackQuery

    from bot.container import BotDependencies
    from bot.integrations.repositories import RepositoryInfo
    from bot.services import BannerGenerator, PreviewDebugRegistry

router = Router(name="post")
logger = get_logger(__name__)

type MessageCoords = tuple[int | None, int | None]


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
    summary: dict[str, object] | None = None
    debug_url: str | None = None
    edit_prompt_chat_id: int | None = None
    edit_prompt_message_id: int | None = None
    edit_request_chat_id: int | None = None
    edit_request_message_id: int | None = None
    edit_status_chat_id: int | None = None
    edit_status_message_id: int | None = None

    @classmethod
    def from_state_data(cls, data: dict[str, object]) -> Self | None:
        try:
            return cls.model_validate(data)
        except ValidationError:
            return None

    def decode_banner(self) -> bytes | None:
        try:
            return base64.b64decode(self.banner_b64, validate=True)
        except (binascii.Error, ValueError):
            return None

    def to_summary(self) -> RepositorySummary | None:
        if self.summary is None:
            return None
        try:
            return RepositorySummary.model_validate(self.summary)
        except ValidationError:
            return None

    def get_cleanup_targets(self) -> list[MessageCoords]:
        return [
            (self.original_chat_id, self.original_message_id),
            (self.prompt_chat_id, self.prompt_message_id),
            (self.command_chat_id, self.command_message_id),
            (self.edit_prompt_chat_id, self.edit_prompt_message_id),
            (self.edit_request_chat_id, self.edit_request_message_id),
            (self.edit_status_chat_id, self.edit_status_message_id),
        ]


@router.message(Command("post"))
@flags.chat_action(action="upload_photo", initial_sleep=0.0)
async def handle_post_command(
    message: Message, command: CommandObject, state: FSMContext, bot_dependencies: BotDependencies
) -> None:
    await _reset_submission_state(state, bot_dependencies.preview_registry)
    args = (command.args or "").strip()
    await state.update_data(command_chat_id=message.chat.id, command_message_id=message.message_id)

    if args:
        await _process_repository(message, args, state, bot_dependencies=bot_dependencies)
        return

    await state.set_state(PostStates.waiting_for_url)
    prompt = await message.answer("Send the GitHub or GitLab repository URL you want to share.")
    await state.update_data(prompt_chat_id=prompt.chat.id, prompt_message_id=prompt.message_id)


@router.message(PostStates.waiting_for_url)
@flags.chat_action(action="upload_photo", initial_sleep=0.0)
async def handle_repository_input(message: Message, state: FSMContext, bot_dependencies: BotDependencies) -> None:
    if not message.text:
        await message.answer("Please send the repository URL as plain text.")
        return
    await _process_repository(message, message.text, state, bot_dependencies=bot_dependencies)


@router.callback_query(
    PostStates.waiting_for_confirmation, SubmissionCallback.filter(F.action == SubmissionAction.PUBLISH)
)
@router.callback_query(
    PostStates.waiting_for_edit_instructions, SubmissionCallback.filter(F.action == SubmissionAction.PUBLISH)
)
@flags.callback_answer(text="Published in @AndroidRepo!")
async def handle_publish_callback(
    callback: CallbackQuery,
    callback_data: SubmissionCallback,
    state: FSMContext,
    bot: Bot,
    bot_dependencies: BotDependencies,
) -> None:
    data = await state.get_data()
    submission = SubmissionData.from_state_data(data)
    registry = bot_dependencies.preview_registry

    if submission is None or submission.submission_id != callback_data.submission_id:
        await callback.answer("This preview expired. Please run /post again.", show_alert=True)
        return

    banner_bytes = submission.decode_banner()
    if banner_bytes is None:
        await callback.answer("Preview data is corrupted. Please start over.", show_alert=True)
        registry.discard(callback_data.submission_id)
        await state.clear()
        return

    preview_message = callback.message
    if not isinstance(preview_message, Message):
        await callback.answer("This callback has no preview context.", show_alert=True)
        registry.discard(callback_data.submission_id)
        await state.clear()
        return

    photo = BufferedInputFile(banner_bytes, filename=f"post-{callback_data.submission_id}.png")

    try:
        await bot.send_photo(chat_id=bot_dependencies.settings.post_channel_id, photo=photo, caption=submission.caption)
    except TelegramBadRequest as exc:
        await callback.answer("Unable to publish post. Please try again.", show_alert=True)
        await logger.aexception("Failed to publish post", exc_info=exc)
        return

    await _cleanup_submission_messages(bot, submission, preview_message)
    registry.discard(callback_data.submission_id)
    await state.clear()


@router.callback_query(
    PostStates.waiting_for_confirmation, SubmissionCallback.filter(F.action == SubmissionAction.CANCEL)
)
@router.callback_query(
    PostStates.waiting_for_edit_instructions, SubmissionCallback.filter(F.action == SubmissionAction.CANCEL)
)
@flags.callback_answer(text="Preview cancelled.")
async def handle_cancel_callback(
    callback: CallbackQuery,
    callback_data: SubmissionCallback,
    state: FSMContext,
    bot: Bot,
    bot_dependencies: BotDependencies,
) -> None:
    data = await state.get_data()
    submission = SubmissionData.from_state_data(data)

    if submission is None or submission.submission_id != callback_data.submission_id:
        await callback.answer("This preview is already closed.")
        return

    preview_message = callback.message if isinstance(callback.message, Message) else None
    await _cleanup_submission_messages(bot, submission, preview_message)
    bot_dependencies.preview_registry.discard(callback_data.submission_id)
    await state.clear()


@router.callback_query(
    PostStates.waiting_for_confirmation, SubmissionCallback.filter(F.action == SubmissionAction.EDIT)
)
@flags.callback_answer(text="Got it! Waiting for your edit request.")
async def handle_edit_callback(
    callback: CallbackQuery,
    callback_data: SubmissionCallback,
    state: FSMContext,
    bot: Bot,
    bot_dependencies: BotDependencies,
) -> None:
    preview_message = callback.message if isinstance(callback.message, Message) else None
    if preview_message is None:
        await callback.answer("This preview is no longer available.", show_alert=True)
        await state.clear()
        return

    data = await state.get_data()
    submission = SubmissionData.from_state_data(data)

    if submission is None or submission.submission_id != callback_data.submission_id:
        await callback.answer("This preview expired. Please run /post again.", show_alert=True)
        return

    repository = bot_dependencies.preview_registry.get(submission.submission_id)
    if repository is None:
        await callback.answer("Repository context is missing. Please restart /post.", show_alert=True)
        await state.clear()
        return

    summary = submission.to_summary()
    if summary is None:
        await callback.answer("Preview data is incomplete. Please restart /post.", show_alert=True)
        await state.clear()
        return

    prompt = await preview_message.answer(
        "Send a message explaining how the preview should change. "
        "You can mention tone tweaks, features to highlight, or text to remove."
    )
    await _track_edit_message(state, bot, prompt, "edit_prompt", submission)
    await state.set_state(PostStates.waiting_for_edit_instructions)


@router.message(PostStates.waiting_for_edit_instructions)
@flags.chat_action(action="upload_photo", initial_sleep=0.0)
async def handle_edit_instructions(
    message: Message, state: FSMContext, bot_dependencies: BotDependencies, bot: Bot
) -> None:
    text = (message.text or "").strip()
    if not text:
        await message.answer("Please describe the desired edits using plain text.")
        return

    data = await state.get_data()
    submission = SubmissionData.from_state_data(data)

    if submission is None:
        await message.answer("This preview expired. Please run /post again.")
        await state.clear()
        return

    repository = bot_dependencies.preview_registry.get(submission.submission_id)
    if repository is None:
        await message.answer("Repository data is unavailable. Please restart /post.")
        await state.clear()
        return

    summary = submission.to_summary()
    if summary is None:
        await message.answer("Summary data is unavailable. Please restart /post.")
        await state.clear()
        return

    await _track_edit_message(state, bot, message, "edit_request", submission)
    await _delete_state_message(bot, submission.edit_prompt_chat_id, submission.edit_prompt_message_id)

    progress = await message.answer("[1/3] Understanding your edit request...")
    await _track_edit_message(state, bot, progress, "edit_status", submission)

    try:
        updated_summary = await bot_dependencies.summary_agent.revise_summary(
            repository=repository, summary=summary, edit_request=text
        )
    except PreviewEditError as exc:
        await logger.awarning("Preview edit request failed", submission_id=submission.submission_id, error=str(exc))
        await _edit_progress(progress, "I couldn't apply that edit. Please try rephrasing your request.")
        return

    await _edit_progress(progress, "[2/3] Updating banner...")
    banner_bytes = await _render_banner(bot_dependencies.banner_generator, repository, updated_summary)

    caption = render_post_caption(repository, updated_summary)
    await _edit_progress(progress, "[3/3] Updating preview message...")

    photo = BufferedInputFile(banner_bytes, filename=f"{repository.name}.png")
    media = InputMediaPhoto(media=photo, caption=caption)
    keyboard = _build_preview_keyboard(submission.submission_id, submission.debug_url).as_markup()

    try:
        await bot.edit_message_media(
            chat_id=submission.preview_chat_id,
            message_id=submission.preview_message_id,
            media=media,
            reply_markup=keyboard,
        )
    except TelegramBadRequest as exc:
        await logger.aexception(
            "Failed to update preview message", submission_id=submission.submission_id, error=str(exc)
        )
        await _edit_progress(progress, "Preview could not be updated. Please try again.")
        return

    await state.update_data(
        caption=caption,
        banner_b64=base64.b64encode(banner_bytes).decode("ascii"),
        summary=updated_summary.model_dump(mode="json"),
        edit_prompt_chat_id=None,
        edit_prompt_message_id=None,
    )
    await state.set_state(PostStates.waiting_for_confirmation)
    await _edit_progress(progress, "Preview updated! You can publish, edit again, or cancel.")


async def _process_repository(
    message: Message, raw_url: str, state: FSMContext, *, bot_dependencies: BotDependencies
) -> None:
    try:
        locator = parse_repository_url(raw_url)
    except RepositoryUrlParseError as exc:
        await message.answer(str(exc))
        return

    progress_message = await message.answer("[1/3] Fetching repository metadata...")

    fetcher = select_fetcher(
        locator, github_fetcher=bot_dependencies.github_fetcher, gitlab_fetcher=bot_dependencies.gitlab_fetcher
    )

    try:
        repository = await fetcher.fetch_repository(locator.owner, locator.name)
    except RepositoryClientError as exc:
        await logger.awarning("Repository fetch failed", url=raw_url, error=str(exc))
        await _edit_progress(progress_message, "Unable to load repository metadata. Please double-check the URL.")
        return

    await _edit_progress(progress_message, "[2/3] Generating AI summary...")

    try:
        summary = await bot_dependencies.summary_agent.summarize(repository)
    except RepositorySummaryError as exc:
        await logger.aexception("Summary generation failed", repo=repository.full_name, error=str(exc))
        await _edit_progress(progress_message, "Could not generate AI summary. Please try again later.")
        return

    await _edit_progress(progress_message, "[3/3] Rendering preview...")

    caption = render_post_caption(repository, summary)
    banner_bytes = await _render_banner(bot_dependencies.banner_generator, repository, summary)
    submission_id = uuid4().hex
    bot_dependencies.preview_registry.save(submission_id, repository)

    debug_url = await _build_debug_link(message, submission_id)

    preview = await message.answer_photo(
        photo=BufferedInputFile(banner_bytes, filename=f"{repository.name}.png"),
        caption=caption,
        reply_markup=_build_preview_keyboard(submission_id, debug_url).as_markup(),
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

    await _delete_message(progress_message)


async def _render_banner(generator: BannerGenerator, repository: RepositoryInfo, summary: RepositorySummary) -> bytes:
    def _sync_generate() -> bytes:
        buffer = generator.generate(summary.project_name or repository.name)
        try:
            return buffer.getvalue()
        finally:
            buffer.close()

    result = await to_thread.run_sync(_sync_generate)
    await logger.ainfo("Generated banner", repo=repository.full_name)
    return result


async def _build_debug_link(message: Message, submission_id: str) -> str | None:
    bot = message.bot
    if bot is None:
        return None
    try:
        payload = build_preview_payload(submission_id)
        return await create_start_link(bot, payload, encode=True)
    except TelegramBadRequest as exc:
        await logger.awarning("Failed to create preview debug deeplink", submission_id=submission_id, error=str(exc))
    return None


def _build_preview_keyboard(submission_id: str, debug_url: str | None) -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="Publish", callback_data=SubmissionCallback(action=SubmissionAction.PUBLISH, submission_id=submission_id)
    )
    builder.button(
        text="Edit", callback_data=SubmissionCallback(action=SubmissionAction.EDIT, submission_id=submission_id)
    )
    builder.button(
        text="Cancel", callback_data=SubmissionCallback(action=SubmissionAction.CANCEL, submission_id=submission_id)
    )
    if debug_url:
        builder.button(text="Inspect Data", url=debug_url)
        builder.adjust(2, 1, 1)
    else:
        builder.adjust(2, 1)
    return builder


async def _track_edit_message(
    state: FSMContext, bot: Bot, message: Message, prefix: str, submission: SubmissionData | None = None
) -> None:
    if submission is not None:
        old_chat_id = getattr(submission, f"{prefix}_chat_id", None)
        old_message_id = getattr(submission, f"{prefix}_message_id", None)
        await _delete_state_message(bot, old_chat_id, old_message_id)

    update: dict[str, int] = {f"{prefix}_chat_id": message.chat.id, f"{prefix}_message_id": message.message_id}
    await state.update_data(update)


async def _delete_state_message(bot: Bot | None, chat_id: int | None, message_id: int | None) -> None:
    if bot is None or chat_id is None or message_id is None:
        return
    with suppress(TelegramBadRequest):
        await bot.delete_message(chat_id=chat_id, message_id=message_id)


async def _edit_progress(message: Message, text: str) -> None:
    with suppress(TelegramBadRequest):
        await message.edit_text(text)


async def _delete_message(message: Message) -> None:
    with suppress(TelegramBadRequest):
        await message.delete()


async def _cleanup_submission_messages(bot: Bot, submission: SubmissionData, preview_message: Message | None) -> None:
    if preview_message:
        with suppress(TelegramBadRequest):
            await preview_message.delete()

    for chat_id, message_id in submission.get_cleanup_targets():
        if chat_id is not None and message_id is not None:
            with suppress(TelegramBadRequest):
                await bot.delete_message(chat_id=chat_id, message_id=message_id)


async def _reset_submission_state(state: FSMContext, registry: PreviewDebugRegistry) -> None:
    data = await state.get_data()
    if submission := SubmissionData.from_state_data(data):
        registry.discard(submission.submission_id)
    await state.clear()
