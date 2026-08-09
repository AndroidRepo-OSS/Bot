from datetime import datetime  # ruff: ignore[typing-only-standard-library-import]
from typing import TYPE_CHECKING

import structlog
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from pydantic import BaseModel, ConfigDict, ValidationError

from androidrepo_bot.posts.models import PostDraft, RegisteredRepository  # ruff: ignore[typing-only-first-party-import]
from androidrepo_bot.repositories.models import (  # ruff: ignore[typing-only-first-party-import]
    RepositoryDetails,
    RepositoryRef,
)

if TYPE_CHECKING:
    from aiogram import Bot
    from aiogram.fsm.context import FSMContext

    from androidrepo_bot.posts.models import PostCreation

logger = structlog.get_logger(__name__)
_SESSION_KEY = "draft_session"
PENDING_PUBLICATION_MESSAGE = (
    "⚠️ This post already reached the channel, but its publication record is "
    "still pending. Use “Publish now” again to finish saving it."
)


class PostDraftState(StatesGroup):
    active = State()
    confirming_publication = State()
    awaiting_download_confirmation = State()


DRAFT_STATES = (
    PostDraftState.active,
    PostDraftState.confirming_publication,
    PostDraftState.awaiting_download_confirmation,
)
_DRAFT_STATE_NAMES = frozenset(state.state for state in DRAFT_STATES)


class PendingPublication(BaseModel):
    channel_id: int
    message_id: int
    published_by_user_id: int
    published_at: datetime

    model_config = ConfigDict(extra="forbid", frozen=True)


class DraftSession(BaseModel):
    owner_id: int
    message_id: int
    repository: RepositoryDetails
    draft: PostDraft
    registered_repository: RegisteredRepository
    notice_message_id: int | None = None
    pending_publication: PendingPublication | None = None

    model_config = ConfigDict(extra="forbid", frozen=True)


class PendingDownloadConfirmation(BaseModel):
    owner_id: int
    repository: RepositoryRef

    model_config = ConfigDict(extra="forbid", frozen=True)


def repository_log_context(session: DraftSession) -> dict[str, str]:
    repository = session.repository.ref
    return {"provider": repository.provider.value, "repository": repository.full_name}


async def save_session(state: FSMContext, *, creation: PostCreation, message_id: int, owner_id: int) -> DraftSession:
    session = DraftSession(
        owner_id=owner_id,
        message_id=message_id,
        repository=creation.repository,
        draft=creation.draft,
        registered_repository=creation.registered_repository,
    )
    await _activate_session(state, session)
    return session


async def add_notice(state: FSMContext, session: DraftSession, notice_message_id: int) -> DraftSession:
    updated = session.model_copy(update={"notice_message_id": notice_message_id})
    await _activate_session(state, updated)
    return updated


async def update_draft(state: FSMContext, session: DraftSession, draft: PostDraft, *, message_id: int) -> DraftSession:
    updated = session.model_copy(update={"draft": draft, "message_id": message_id, "pending_publication": None})
    await _activate_session(state, updated)
    return updated


async def mark_publication_copied(
    state: FSMContext, session: DraftSession, publication: PendingPublication
) -> DraftSession:
    updated = session.model_copy(update={"pending_publication": publication})
    await _store_session(state, updated)
    return updated


async def request_publication_confirmation(state: FSMContext) -> None:
    await state.set_state(PostDraftState.confirming_publication)


async def return_to_draft(state: FSMContext) -> None:
    await state.set_state(PostDraftState.active)


async def request_download_confirmation(
    state: FSMContext, *, repository: RepositoryRef, owner_id: int
) -> PendingDownloadConfirmation:
    pending = PendingDownloadConfirmation(owner_id=owner_id, repository=repository)
    await state.set_state(PostDraftState.awaiting_download_confirmation)
    await state.set_data({"download_confirmation": pending.model_dump(mode="json")})
    return pending


async def load_download_confirmation(state: FSMContext, owner_id: int) -> PendingDownloadConfirmation | None:
    if await state.get_state() != PostDraftState.awaiting_download_confirmation.state:
        return None
    payload = (await state.get_data()).get("download_confirmation")
    try:
        pending = PendingDownloadConfirmation.model_validate(payload)
    except ValidationError:
        logger.warning("Discarding invalid download confirmation data")
        return None
    return pending if pending.owner_id == owner_id else None


async def load_session(state: FSMContext, owner_id: int) -> DraftSession | None:
    if await state.get_state() not in _DRAFT_STATE_NAMES:
        return None
    payload = (await state.get_data()).get(_SESSION_KEY)
    try:
        session = DraftSession.model_validate(payload)
    except ValidationError:
        logger.warning("Discarding invalid draft session data")
        return None
    if session.owner_id != owner_id:
        return None
    return session


async def active_draft_context(callback: CallbackQuery, state: FSMContext) -> tuple[Message, DraftSession] | None:
    message = callback.message
    if not isinstance(message, Message):
        await reject_callback(callback)
        return None
    session = await load_session(state, callback.from_user.id)
    if session is None or session.message_id != message.message_id:
        await reject_callback(callback)
        return None
    return message, session


async def reject_callback(callback: CallbackQuery) -> None:
    try:
        await callback.answer("This draft is no longer active. Create a new one with /post.", show_alert=True)
    except TelegramAPIError:
        logger.debug("Could not answer rejected draft callback", exc_info=True)


async def delete_draft_messages(bot: Bot, chat_id: int, session: DraftSession) -> None:
    for message_id in (session.message_id, session.notice_message_id):
        if message_id is None:
            continue
        try:
            await bot.delete_message(chat_id=chat_id, message_id=message_id)
        except TelegramAPIError:
            logger.debug("Draft message was unavailable", chat_id=chat_id, message_id=message_id, exc_info=True)


async def deactivate_previous(message: Message, state: FSMContext, bot: Bot) -> DraftSession | None:
    user = message.from_user
    if user is None:
        await state.clear()
        return None
    session = await load_session(state, user.id)
    if session is None:
        await state.clear()
        return None
    try:
        await bot.edit_message_reply_markup(chat_id=message.chat.id, message_id=session.message_id, reply_markup=None)
    except TelegramAPIError:
        logger.debug("Previous draft controls were unavailable", exc_info=True)
    await state.clear()
    return session


async def _activate_session(state: FSMContext, session: DraftSession) -> None:
    await state.set_state(PostDraftState.active)
    await _store_session(state, session)


async def _store_session(state: FSMContext, session: DraftSession) -> None:
    payload = session.model_dump(mode="json")
    assert isinstance(payload, dict)
    await state.set_data({_SESSION_KEY: payload})
