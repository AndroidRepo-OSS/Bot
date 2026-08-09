from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog
from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import StateFilter
from aiogram.utils.formatting import Bold, Text
from sqlalchemy.exc import SQLAlchemyError

from androidrepo_bot.errors import GenerationError
from androidrepo_bot.posts.models import PublicationRecord
from androidrepo_bot.posts.state import (
    PENDING_PUBLICATION_MESSAGE,
    PendingPublication,
    PostDraftState,
    active_draft_context,
    delete_draft_messages,
    mark_publication_copied,
    reject_callback,
    request_publication_confirmation,
    return_to_draft,
    update_draft,
)
from androidrepo_bot.posts.ui import (
    POST_CALLBACK_PREFIX,
    DraftProgress,
    PostAction,
    PostCallback,
    draft_keyboard,
    publish_confirmation_keyboard,
    published_post_keyboard,
    render_post_media,
)

if TYPE_CHECKING:
    from aiogram.fsm.context import FSMContext
    from aiogram.types import CallbackQuery, Message

    from androidrepo_bot.admin import AdminLog
    from androidrepo_bot.config import Settings
    from androidrepo_bot.media import BannerImage
    from androidrepo_bot.posts.models import PostDraft
    from androidrepo_bot.posts.service import PostService

logger = structlog.get_logger(__name__)
router = Router(name=__name__)


@router.callback_query(PostCallback.filter(F.action == PostAction.PUBLISH), StateFilter(PostDraftState.active))
async def handle_publish_request(callback: CallbackQuery, state: FSMContext) -> None:
    context = await active_draft_context(callback, state)
    if context is None:
        return
    message, session = context
    if session.pending_publication is not None:
        await message.answer(PENDING_PUBLICATION_MESSAGE)
        await _answer(callback, "Finish saving the existing publication.")
        return
    await message.edit_reply_markup(reply_markup=publish_confirmation_keyboard(session.draft))
    await request_publication_confirmation(state)
    await _answer(callback, "Ready to publish. Confirm below.")


@router.callback_query(
    PostCallback.filter(F.action == PostAction.CONFIRM_PUBLISH), StateFilter(PostDraftState.confirming_publication)
)
async def handle_publish_confirmation(
    callback: CallbackQuery, state: FSMContext, settings: Settings, admin_log: AdminLog, post_service: PostService
) -> None:
    context = await active_draft_context(callback, state)
    if context is None:
        return
    message, session = context
    await _answer(callback, "Publishing…")

    async with post_service.publication_lock(session.registered_repository.id):
        context = await active_draft_context(callback, state)
        if context is None:
            return
        message, session = context
        pending = session.pending_publication
        if pending is None:
            cooldown = await post_service.check_publication_cooldown(
                session.registered_repository, requested_by_user_id=callback.from_user.id
            )
            if not cooldown.allowed:
                await message.edit_reply_markup(reply_markup=draft_keyboard(session.draft))
                await return_to_draft(state)
                await message.answer(**_publication_cooldown_message(cooldown.blocked_until).as_kwargs())
                return

            try:
                copied = await admin_log.bot.copy_message(
                    chat_id=settings.channel_id,
                    from_chat_id=message.chat.id,
                    message_id=session.message_id,
                    reply_markup=published_post_keyboard(session.draft),
                )
            except TelegramAPIError as error:
                await message.answer("⚠️ Could not publish. Check the bot's channel permissions and try again.")
                await admin_log.publication_failed(
                    user=callback.from_user, session=session, error_type=type(error).__name__
                )
                return

            pending = PendingPublication(
                channel_id=settings.channel_id,
                message_id=copied.message_id,
                published_by_user_id=callback.from_user.id,
                published_at=datetime.now(UTC),
            )
            session = await mark_publication_copied(state, session, pending)

        try:
            await post_service.record_publication(
                PublicationRecord(
                    repository=session.registered_repository,
                    title=session.draft.title,
                    tags=tuple(tag.value for tag in session.draft.tags),
                    created_by_user_id=pending.published_by_user_id,
                    channel_id=pending.channel_id,
                    channel_message_id=pending.message_id,
                    published_at=pending.published_at,
                )
            )
        except SQLAlchemyError as error:
            await message.answer(
                "⚠️ The post reached the channel, but its publication record "
                "could not be saved. Use “Publish now” again to retry the record; "
                "the channel post will not be copied twice."
            )
            await admin_log.publication_failed(
                user=callback.from_user, session=session, error_type=type(error).__name__
            )
            return

        await state.clear()

    await delete_draft_messages(admin_log.bot, message.chat.id, session)
    await message.answer("✅ Published to the channel.")
    await admin_log.post_published(
        user=callback.from_user, session=session, channel_id=pending.channel_id, message_id=pending.message_id
    )


@router.callback_query(
    PostCallback.filter(F.action == PostAction.BACK), StateFilter(PostDraftState.confirming_publication)
)
async def handle_publish_back(callback: CallbackQuery, state: FSMContext) -> None:
    context = await active_draft_context(callback, state)
    if context is None:
        return
    message, session = context
    if session.pending_publication is not None:
        await message.answer(PENDING_PUBLICATION_MESSAGE)
        await _answer(callback, "The published receipt must be saved first.")
        return
    await message.edit_reply_markup(reply_markup=draft_keyboard(session.draft))
    await return_to_draft(state)
    await _answer(callback, "Publication cancelled. Draft kept.")


@router.callback_query(PostCallback.filter(F.action == PostAction.REGENERATE), StateFilter(PostDraftState.active))
async def handle_regenerate(callback: CallbackQuery, state: FSMContext, post_service: PostService) -> None:
    context = await active_draft_context(callback, state)
    if context is None:
        return
    message, session = context
    await _answer(callback, "Regenerating draft…")
    progress = await DraftProgress.start(message)
    await progress.complete_step()
    try:
        draft = await post_service.regenerate(
            session.repository, allow_missing_download=session.draft.download_url is None
        )
        await progress.complete_step()
        banner = await post_service.render_banner(draft, session.repository)
        await progress.complete_step()
        replacement = await _send_replacement(message, draft, banner)
    except GenerationError, ValueError, TelegramAPIError:
        await progress.fail(
            Text(Bold("Could not regenerate the draft"), "\n", "The current draft is still available. Try again later.")
        )
        return

    await update_draft(state, session, draft, message_id=replacement.message_id)
    try:
        await message.delete()
    except TelegramAPIError:
        logger.debug(
            "Previous draft remained after successful regeneration", draft_message_id=session.message_id, exc_info=True
        )
    await progress.complete_step()
    await progress.delete()


@router.callback_query(
    PostCallback.filter(F.action == PostAction.CANCEL),
    StateFilter(PostDraftState.active, PostDraftState.confirming_publication),
)
async def handle_cancel(callback: CallbackQuery, state: FSMContext, bot: Bot, admin_log: AdminLog) -> None:
    context = await active_draft_context(callback, state)
    if context is None:
        return
    message, session = context
    if session.pending_publication is not None:
        await message.answer(PENDING_PUBLICATION_MESSAGE)
        await _answer(callback, "The published receipt must be saved first.")
        return
    await _answer(callback, "Draft cancelled.")
    await state.clear()
    await delete_draft_messages(bot, message.chat.id, session)
    await message.answer("🗑️ Draft cancelled.")
    await admin_log.draft_cancelled(user=callback.from_user, session=session, reason="Cancelled from draft controls")


@router.callback_query(F.data.startswith(f"{POST_CALLBACK_PREFIX}:"))
async def handle_stale_callback(callback: CallbackQuery) -> None:
    await reject_callback(callback)


async def _answer(callback: CallbackQuery, text: str) -> None:
    try:
        await callback.answer(text)
    except TelegramAPIError:
        logger.debug("Could not answer callback query", callback_id=callback.id, exc_info=True)


async def _send_replacement(message: Message, draft: PostDraft, banner: BannerImage) -> Message:
    media = render_post_media(draft, banner)
    return await message.answer_photo(
        photo=media.media,
        caption=media.caption,
        caption_entities=media.caption_entities,
        reply_markup=draft_keyboard(draft),
    )


def _publication_cooldown_message(blocked_until: datetime | None) -> Text:
    if blocked_until is None:
        return Text(Bold("Publication cooldown"), "\n", "This repository was published recently. Try again later.")
    return Text(
        Bold("Publication cooldown"),
        "\n",
        f"Another draft published this repository first. Try again after {blocked_until:%Y-%m-%d}.",
    )
