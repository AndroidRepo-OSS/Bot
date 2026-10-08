from typing import TYPE_CHECKING

from aiogram import F, Router, flags
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import StateFilter
from aiogram.utils.callback_answer import CallbackAnswerMiddleware
from aiogram.utils.formatting import Bold, Text, as_list
from sqlalchemy.exc import SQLAlchemyError

from androidrepo_bot.db.publications import BlockedPublication, PublicationInProgress
from androidrepo_bot.posts.publication import PublicationCompensated, PublicationCompleted, PublicationRecoveryRequired
from androidrepo_bot.posts.state import DraftState, PostDraftState
from androidrepo_bot.posts.telegram import (
    POST_CALLBACK_PREFIX,
    PostAction,
    PostCallback,
    active_draft,
    delete_draft_messages,
    draft_keyboard,
    publish_confirmation_keyboard,
)

if TYPE_CHECKING:
    from datetime import datetime

    from aiogram import Bot
    from aiogram.types import CallbackQuery, Message

    from androidrepo_bot.admin import AdminLog
    from androidrepo_bot.posts.drafts import DraftWorkflow
    from androidrepo_bot.posts.publication import PublicationWorkflow
    from androidrepo_bot.posts.state import DraftSession
    from androidrepo_bot.posts.telegram import DraftContext

router = Router(name=__name__)
router.callback_query.middleware(CallbackAnswerMiddleware())


@router.callback_query(PostCallback.filter(F.action == PostAction.PUBLISH), PostDraftState.active, active_draft)
@flags.callback_answer(text="Ready to publish. Confirm below.")
async def handle_publish_request(callback: CallbackQuery, draft_context: DraftContext) -> None:
    message, session, state = draft_context
    await message.edit_reply_markup(reply_markup=publish_confirmation_keyboard(session.draft))
    await state.save(session, status=PostDraftState.confirming_publication)


@router.callback_query(
    PostCallback.filter(F.action == PostAction.CONFIRM_PUBLISH), PostDraftState.confirming_publication, active_draft
)
@flags.callback_answer(pre=True, text="Publishing…")
async def handle_publish_confirmation(
    callback: CallbackQuery,
    draft_context: DraftContext,
    admin_log: AdminLog,
    publications: PublicationWorkflow,
    bot: Bot,
) -> None:
    message, session, state = draft_context
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

    user = callback.from_user
    match outcome:
        case BlockedPublication(cooldown):
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
            await delete_draft_messages(bot, message.chat.id, session)
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
    PostCallback.filter(F.action == PostAction.BACK), PostDraftState.confirming_publication, active_draft
)
@flags.callback_answer(text="Publication cancelled. Draft kept.")
async def handle_publish_back(callback: CallbackQuery, draft_context: DraftContext) -> None:
    message, session, state = draft_context
    await _restore_active_draft(message, state, session)


@router.callback_query(PostCallback.filter(F.action == PostAction.REGENERATE), PostDraftState.active, active_draft)
@flags.callback_answer(pre=True, text="Regenerating draft…")
async def handle_regenerate(callback: CallbackQuery, draft_context: DraftContext, drafts: DraftWorkflow) -> None:
    message, session, state = draft_context
    await drafts.revise(message, state, session)


@router.callback_query(
    PostCallback.filter(F.action == PostAction.CANCEL),
    StateFilter(PostDraftState.active, PostDraftState.confirming_publication),
    active_draft,
)
@flags.callback_answer(pre=True, text="Draft cancelled.")
async def handle_cancel(callback: CallbackQuery, draft_context: DraftContext, admin_log: AdminLog, bot: Bot) -> None:
    message, session, state = draft_context
    await state.clear()
    await delete_draft_messages(bot, message.chat.id, session)
    await message.answer("🗑️ Draft cancelled.")
    await admin_log.draft_cancelled(user=callback.from_user, session=session, reason="Cancelled from draft controls")


@router.callback_query(F.data.startswith(f"{POST_CALLBACK_PREFIX}:"))
@flags.callback_answer(text="This draft is no longer active. Create a new one with /post.", show_alert=True)
async def handle_stale_callback(callback: CallbackQuery) -> None:
    """The callback middleware explains rejected or expired draft controls."""


async def _restore_active_draft(message: Message, state: DraftState, session: DraftSession) -> None:
    await message.edit_reply_markup(reply_markup=draft_keyboard(session.draft))
    await state.save(session)


def _publication_cooldown_message(blocked_until: datetime | None) -> Text:
    if blocked_until is None:
        return as_list(Bold("Publication cooldown"), "This repository was published recently. Try again later.")
    return as_list(
        Bold("Publication cooldown"),
        f"Another draft published this repository first. Try again after {blocked_until:%Y-%m-%d}.",
    )
