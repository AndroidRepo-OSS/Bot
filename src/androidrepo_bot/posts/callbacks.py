from typing import TYPE_CHECKING

import structlog
from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import StateFilter
from aiogram.utils.formatting import Bold, Text, as_list
from sqlalchemy.exc import SQLAlchemyError

from androidrepo_bot.posts.publication import (
    PublicationBlocked,
    PublicationCompensated,
    PublicationCompleted,
    PublicationInProgress,
    PublicationOutcome,
    PublicationRecoveryRequired,
)
from androidrepo_bot.posts.state import DraftState, PostDraftState
from androidrepo_bot.posts.telegram import active_draft_context, bound_bot, delete_draft_messages, reject_callback
from androidrepo_bot.posts.ui import (
    POST_CALLBACK_PREFIX,
    PostAction,
    PostCallback,
    draft_keyboard,
    publish_confirmation_keyboard,
)

if TYPE_CHECKING:
    from datetime import datetime

    from aiogram.fsm.context import FSMContext
    from aiogram.types import CallbackQuery, Message, User

    from androidrepo_bot.admin import AdminLog
    from androidrepo_bot.posts.drafts import DraftWorkflow
    from androidrepo_bot.posts.publication import PublicationWorkflow
    from androidrepo_bot.posts.state import DraftSession

logger = structlog.get_logger(__name__)
router = Router(name=__name__)


@router.callback_query(PostCallback.filter(F.action == PostAction.PUBLISH), StateFilter(PostDraftState.active))
async def handle_publish_request(callback: CallbackQuery, state: FSMContext) -> None:
    context = await active_draft_context(callback, state)
    if context is None:
        return
    message, session = context
    await message.edit_reply_markup(reply_markup=publish_confirmation_keyboard(session.draft))
    await DraftState(state).save(session.confirming_publication())
    await _answer(callback, "Ready to publish. Confirm below.")


@router.callback_query(
    PostCallback.filter(F.action == PostAction.CONFIRM_PUBLISH), StateFilter(PostDraftState.confirming_publication)
)
async def handle_publish_confirmation(
    callback: CallbackQuery, state: FSMContext, admin_log: AdminLog, publications: PublicationWorkflow
) -> None:
    context = await active_draft_context(callback, state)
    if context is None:
        return
    message, session = context
    await _answer(callback, "Publishing…")

    try:
        outcome = await publications.publish(
            session, source_chat_id=message.chat.id, actor_user_id=callback.from_user.id
        )
    except TelegramAPIError as error:
        await message.answer("⚠️ Could not publish. Check the bot's channel permissions and try again.")
        await admin_log.publication_failed(user=callback.from_user, session=session, error_type=type(error).__name__)
        return
    except SQLAlchemyError as error:
        await message.answer("⚠️ Publication storage is temporarily unavailable. No channel post was sent.")
        await admin_log.publication_failed(user=callback.from_user, session=session, error_type=type(error).__name__)
        return

    await _handle_publication_outcome(
        outcome, context=context, state=DraftState(state), user=callback.from_user, admin_log=admin_log
    )


async def _handle_publication_outcome(
    outcome: PublicationOutcome,
    *,
    context: tuple[Message, DraftSession],
    state: DraftState,
    user: User,
    admin_log: AdminLog,
) -> None:
    message, session = context
    match outcome:
        case PublicationBlocked(cooldown):
            await _restore_active_draft(message, state, session)
            await message.answer(**_publication_cooldown_message(cooldown.blocked_until).as_kwargs())
        case PublicationInProgress():
            await message.answer("⏳ Another publication attempt for this repository is still in progress.")
        case PublicationCompensated(error_type=error_type):
            await _restore_active_draft(message, state, session)
            await message.answer("⚠️ Publication could not be recorded, so the channel copy was removed. Try again.")
            await admin_log.publication_failed(user=user, session=session, error_type=error_type)
        case PublicationRecoveryRequired(operation_id=operation_id, error_type=error_type, receipt=receipt):
            visible_command = (
                f"/reconcile {operation_id} {receipt.channel_message_id} {receipt.published_at.isoformat()}"
                if receipt is not None
                else f"/reconcile {operation_id} <channel-message-id> <ISO-8601-publication-time>"
            )
            await message.answer(
                "🚨 Publication delivery is unresolved. Inspect the channel before continuing with this repository. "
                f"If visible: {visible_command}. If absent: /reconcile {operation_id} absent."
            )
            await admin_log.publication_recovery_required(
                user=user, session=session, operation_id=operation_id, error_type=error_type, receipt=receipt
            )
        case PublicationCompleted(receipt=receipt, reconciled=reconciled):
            await state.clear()
            await delete_draft_messages(bound_bot(message), message.chat.id, session)
            if reconciled:
                await message.answer(
                    "⚠️ Published to the channel after recovering a persistence or deletion failure. "
                    "The publication record and cooldown were reconciled."
                )
            else:
                await message.answer("✅ Published to the channel.")
            await admin_log.post_published(
                user=user,
                session=session,
                channel_id=receipt.channel_id,
                message_id=receipt.channel_message_id,
                reconciled=reconciled,
            )


@router.callback_query(
    PostCallback.filter(F.action == PostAction.BACK), StateFilter(PostDraftState.confirming_publication)
)
async def handle_publish_back(callback: CallbackQuery, state: FSMContext) -> None:
    context = await active_draft_context(callback, state)
    if context is None:
        return
    message, session = context
    await _restore_active_draft(message, DraftState(state), session)
    await _answer(callback, "Publication cancelled. Draft kept.")


@router.callback_query(PostCallback.filter(F.action == PostAction.REGENERATE), StateFilter(PostDraftState.active))
async def handle_regenerate(callback: CallbackQuery, state: FSMContext, drafts: DraftWorkflow) -> None:
    context = await active_draft_context(callback, state)
    if context is None:
        return
    message, session = context
    await _answer(callback, "Regenerating draft…")
    await drafts.revise(message, DraftState(state), session)


@router.callback_query(
    PostCallback.filter(F.action == PostAction.CANCEL),
    StateFilter(PostDraftState.active, PostDraftState.confirming_publication),
)
async def handle_cancel(callback: CallbackQuery, state: FSMContext, admin_log: AdminLog) -> None:
    context = await active_draft_context(callback, state)
    if context is None:
        return
    message, session = context
    await _answer(callback, "Draft cancelled.")
    await DraftState(state).clear()
    await delete_draft_messages(bound_bot(message), message.chat.id, session)
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


async def _restore_active_draft(message: Message, state: DraftState, session: DraftSession) -> None:
    await message.edit_reply_markup(reply_markup=draft_keyboard(session.draft))
    await state.save(session.active())


def _publication_cooldown_message(blocked_until: datetime | None) -> Text:
    if blocked_until is None:
        return as_list(Bold("Publication cooldown"), "This repository was published recently. Try again later.")
    return as_list(
        Bold("Publication cooldown"),
        f"Another draft published this repository first. Try again after {blocked_until:%Y-%m-%d}.",
    )
