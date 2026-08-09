from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import TYPE_CHECKING

import structlog
from aiogram import Bot, F, Router, flags
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandObject, StateFilter
from aiogram.types import Message
from aiogram.utils.chat_action import ChatActionMiddleware
from aiogram.utils.formatting import Bold, BotCommand, Text
from sqlalchemy.exc import SQLAlchemyError

from androidrepo_bot.errors import (
    ExternalServiceError,
    ExternalServiceTimeoutError,
    GenerationError,
    MissingDownloadSourceError,
    NotAndroidProjectError,
    RateLimitError,
    RepositoryAccessError,
    RepositoryNotFoundError,
)
from androidrepo_bot.posts.models import CooldownBlockedError, PublicationCooldown
from androidrepo_bot.posts.state import (
    DRAFT_STATES,
    PENDING_PUBLICATION_MESSAGE,
    PostDraftState,
    add_notice,
    deactivate_previous,
    delete_draft_messages,
    load_download_confirmation,
    load_session,
    request_download_confirmation,
    save_session,
)
from androidrepo_bot.posts.ui import (
    DOWNLOAD_CALLBACK_PREFIX,
    DownloadDecision,
    DownloadDecisionCallback,
    DraftProgress,
    draft_keyboard,
    missing_download_keyboard,
    render_post_media,
)
from androidrepo_bot.repositories import RepositoryUrlError, parse_repository_url

if TYPE_CHECKING:
    from aiogram.fsm.context import FSMContext
    from aiogram.types import CallbackQuery

    from androidrepo_bot.admin import AdminLog
    from androidrepo_bot.media import BannerImage
    from androidrepo_bot.posts.models import PostCreation
    from androidrepo_bot.posts.service import PostService
    from androidrepo_bot.posts.state import DraftSession
    from androidrepo_bot.repositories.models import RepositoryRef

logger = structlog.get_logger(__name__)
router = Router(name=__name__)
router.message.middleware(ChatActionMiddleware())


@dataclass(frozen=True, slots=True)
class _DraftRequest:
    repository: RepositoryRef
    owner_id: int
    allow_missing_download: bool = False


@router.message(Command("cancel"), StateFilter(*DRAFT_STATES))
async def handle_cancel_command(message: Message, state: FSMContext, bot: Bot, admin_log: AdminLog) -> None:
    user = message.from_user
    session = await load_session(state, user.id) if user is not None else None
    if session is not None and session.pending_publication is not None:
        await message.answer(PENDING_PUBLICATION_MESSAGE)
        return
    if session is not None:
        await delete_draft_messages(bot, message.chat.id, session)
    await state.clear()
    await message.answer("🗑️ Draft cancelled.")
    if user is not None and session is not None:
        await admin_log.draft_cancelled(user=user, session=session, reason="Cancelled with /cancel")


@router.message(Command("post"))
@flags.chat_action(initial_sleep=1.0, action="upload_photo")
async def handle_post(  # ruff: ignore[too-many-return-statements]
    message: Message, command: CommandObject, state: FSMContext, post_service: PostService, admin_log: AdminLog
) -> None:
    user = message.from_user
    if user is None:
        await state.clear()
        await message.answer("⚠️ This command is only available to user accounts.")
        return
    repository = await _parse_repository(message, command)
    if repository is None:
        return
    current = await load_session(state, user.id)
    if current is not None and current.pending_publication is not None:
        await message.answer(PENDING_PUBLICATION_MESSAGE)
        return

    previous = await deactivate_previous(message, state, admin_log.bot)
    if previous is not None:
        await admin_log.draft_cancelled(user=user, session=previous, reason="Replaced by a new /post command")

    progress = await DraftProgress.start(message)
    started_at = perf_counter()
    try:
        creation, banner, draft_message_id = await _prepare_draft(
            message, post_service, progress, _DraftRequest(repository=repository, owner_id=user.id)
        )
        session = await save_session(state, creation=creation, message_id=draft_message_id, owner_id=user.id)
    except NotAndroidProjectError as error:
        await state.clear()
        await progress.fail(_error_message("Project is not related to Android", str(error)))
        await admin_log.draft_creation_failed(
            user=user,
            repository=repository,
            duration_seconds=perf_counter() - started_at,
            error_type=type(error).__name__,
        )
        return
    except MissingDownloadSourceError as error:
        await progress.delete()
        await request_download_confirmation(state, repository=repository, owner_id=user.id)
        try:
            await message.answer(
                **Text(
                    "⚠️ ",
                    Bold("No official download source found"),
                    "\n",
                    str(error),
                    "\n\nGenerate the post without a Download button?",
                ).as_kwargs(),
                reply_markup=missing_download_keyboard(),
            )
        except TelegramAPIError:
            await state.clear()
            raise
        return
    except CooldownBlockedError as error:
        await state.clear()
        await progress.fail(_cooldown_message(error.cooldown))
        return
    except (RepositoryAccessError, GenerationError, SQLAlchemyError, TelegramAPIError, ValueError) as error:
        duration_seconds = perf_counter() - started_at
        await state.clear()
        await progress.fail(_workflow_error_message(error))
        await admin_log.draft_creation_failed(
            user=user, repository=repository, duration_seconds=duration_seconds, error_type=type(error).__name__
        )
        return

    session = await _finish_draft(message, state, progress, creation, session)
    await admin_log.draft_created(
        user=user, session=session, duration_seconds=perf_counter() - started_at, banner_artwork=banner.artwork_id
    )


async def _prepare_draft(
    message: Message, post_service: PostService, progress: DraftProgress, request: _DraftRequest
) -> tuple[PostCreation, BannerImage, int]:
    creation = await post_service.create(
        request.repository,
        requested_by_user_id=request.owner_id,
        progress=progress.complete_step,
        allow_missing_download=request.allow_missing_download,
    )
    banner = await post_service.render_banner(creation.draft, creation.repository)
    await progress.complete_step()
    media = render_post_media(creation.draft, banner)
    draft_message = await message.answer_photo(
        photo=media.media,
        caption=media.caption,
        caption_entities=media.caption_entities,
        reply_markup=draft_keyboard(creation.draft),
    )
    return creation, banner, draft_message.message_id


@router.callback_query(
    DownloadDecisionCallback.filter(F.action == DownloadDecision.GENERATE),
    StateFilter(PostDraftState.awaiting_download_confirmation),
)
async def handle_generate_without_download(
    callback: CallbackQuery, state: FSMContext, post_service: PostService, admin_log: AdminLog
) -> None:
    pending = await load_download_confirmation(state, callback.from_user.id)
    message = callback.message
    if pending is None or not isinstance(message, Message):
        await callback.answer("This confirmation is no longer active.", show_alert=True)
        return

    await callback.answer("Generating without a download source…")
    await message.edit_reply_markup(reply_markup=None)
    progress = await DraftProgress.start(message)
    started_at = perf_counter()
    try:
        creation, banner, draft_message_id = await _prepare_draft(
            message,
            post_service,
            progress,
            _DraftRequest(repository=pending.repository, owner_id=callback.from_user.id, allow_missing_download=True),
        )
        session = await save_session(
            state, creation=creation, message_id=draft_message_id, owner_id=callback.from_user.id
        )
    except CooldownBlockedError as error:
        await state.clear()
        await progress.fail(_cooldown_message(error.cooldown))
        return
    except (RepositoryAccessError, GenerationError, SQLAlchemyError, TelegramAPIError, ValueError) as error:
        await state.clear()
        await progress.fail(_workflow_error_message(error))
        await admin_log.draft_creation_failed(
            user=callback.from_user,
            repository=pending.repository,
            duration_seconds=perf_counter() - started_at,
            error_type=type(error).__name__,
        )
        return

    session = await _finish_draft(message, state, progress, creation, session)
    try:
        await message.delete()
    except TelegramAPIError:
        logger.debug("Download warning message remained after draft generation", exc_info=True)
    await admin_log.draft_created(
        user=callback.from_user,
        session=session,
        duration_seconds=perf_counter() - started_at,
        banner_artwork=banner.artwork_id,
    )


@router.callback_query(
    DownloadDecisionCallback.filter(F.action == DownloadDecision.CANCEL),
    StateFilter(PostDraftState.awaiting_download_confirmation),
)
async def handle_cancel_without_download(callback: CallbackQuery, state: FSMContext) -> None:
    pending = await load_download_confirmation(state, callback.from_user.id)
    message = callback.message
    if pending is None or not isinstance(message, Message):
        await callback.answer("This confirmation is no longer active.", show_alert=True)
        return
    await state.clear()
    await message.edit_reply_markup(reply_markup=None)
    await callback.answer("Post generation cancelled.")
    await message.answer("🗑️ Post generation cancelled.")


@router.callback_query(F.data.startswith(f"{DOWNLOAD_CALLBACK_PREFIX}:"))
async def handle_stale_download_confirmation(callback: CallbackQuery) -> None:
    await callback.answer("This confirmation is no longer active.", show_alert=True)


async def _parse_repository(message: Message, command: CommandObject) -> RepositoryRef | None:
    if not command.args:
        await message.answer(
            **Text(
                Bold("Create a repository post"),
                "\n",
                "Send a public GitHub or GitLab repository URL:",
                "\n",
                BotCommand("/post"),
                " https://github.com/owner/repository",
            ).as_kwargs()
        )
        return None
    try:
        return parse_repository_url(command.args)
    except RepositoryUrlError as error:
        await message.answer(**Text("⚠️ ", Bold("Invalid repository URL"), "\n", str(error)).as_kwargs())
        return None


async def _finish_draft(
    message: Message, state: FSMContext, progress: DraftProgress, creation: PostCreation, session: DraftSession
) -> DraftSession:
    if creation.repository.readme is None:
        try:
            notice = await message.answer("⚠️ No README was available, so this draft uses repository metadata only.")
        except TelegramAPIError:
            logger.warning("Could not send missing README notice", exc_info=True)
        else:
            session = await add_notice(state, session, notice.message_id)

    await progress.complete_step()
    await progress.delete()
    return session


def _cooldown_message(cooldown: PublicationCooldown) -> Text:
    if cooldown.blocked_until is None:
        return Text(Bold("Publication cooldown"), "\n", "This repository was published recently. Try again later.")
    return Text(
        Bold("Publication cooldown"),
        "\n",
        f"This repository was published recently. Try again after {cooldown.blocked_until:%Y-%m-%d}.",
    )


def _workflow_error_message(error: Exception) -> Text:
    if isinstance(error, RepositoryNotFoundError):
        return _error_message("Repository not found", "Check that the URL is public and spelled correctly.")
    if isinstance(error, RateLimitError):
        return _error_message("Provider rate limit", "Try again later.")
    if isinstance(error, ExternalServiceTimeoutError):
        return _error_message("Provider took too long", "Try again shortly.")
    if isinstance(error, ExternalServiceError):
        return _error_message("Provider temporarily unavailable", "Try again later.")
    return _error_message("Could not create the post draft", "Try again later.")


def _error_message(heading: str, action: str) -> Text:
    return Text(Bold(heading), "\n", action)
