from datetime import datetime
from typing import TYPE_CHECKING

import structlog
from aiogram import Bot, F, Router, flags
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandObject, StateFilter
from aiogram.types import Message
from aiogram.utils.chat_action import ChatActionMiddleware
from aiogram.utils.formatting import Bold, BotCommand, Text, as_list
from sqlalchemy.exc import SQLAlchemyError

from androidrepo_bot.posts.state import DraftState, PostDraftState
from androidrepo_bot.posts.telegram import delete_draft_messages
from androidrepo_bot.posts.ui import DOWNLOAD_CALLBACK_PREFIX, DownloadDecision, DownloadDecisionCallback
from androidrepo_bot.repositories.parsing import RepositoryUrlError, parse_repository_url

if TYPE_CHECKING:
    from aiogram.fsm.context import FSMContext
    from aiogram.types import CallbackQuery

    from androidrepo_bot.admin import AdminLog
    from androidrepo_bot.posts.drafts import DraftWorkflow
    from androidrepo_bot.posts.publication import PublicationWorkflow
    from androidrepo_bot.repositories.models import RepositoryRef

logger = structlog.get_logger(__name__)
router = Router(name=__name__)
router.message.middleware(ChatActionMiddleware())


@router.message(Command("reconcile"))
async def handle_reconcile_command(message: Message, command: CommandObject, publications: PublicationWorkflow) -> None:
    decision = parse_reconciliation(command.args)
    if decision is None:
        await message.answer(
            "Usage: /reconcile <operation-id> absent, or "
            "/reconcile <operation-id> <channel-message-id> <ISO-8601-publication-time>"
        )
        return
    operation_id, channel_message_id, published_at = decision
    try:
        receipt = await publications.reconcile(
            operation_id, channel_message_id=channel_message_id, published_at=published_at
        )
    except (SQLAlchemyError, ValueError) as error:
        logger.warning(
            "Publication reconciliation failed",
            operation_id=operation_id,
            error_type=type(error).__name__,
            exc_info=True,
        )
        await message.answer(f"⚠️ Could not reconcile operation #{operation_id}: {error}")
        return
    if receipt is None:
        await message.answer(f"✅ Operation #{operation_id} closed with no visible Publication.")
    else:
        await message.answer(
            f"✅ Publication record reconciled for channel message #{receipt.channel_message_id}; cooldown is active."
        )


@router.message(Command("cancel"), StateFilter(PostDraftState))
async def handle_cancel_command(message: Message, state: FSMContext, bot: Bot, admin_log: AdminLog) -> None:
    drafts = DraftState(state)
    session = await drafts.load() if message.from_user is not None else None
    if session is not None:
        await delete_draft_messages(bot, message.chat.id, session)
    await drafts.clear()
    await message.answer("🗑️ Draft cancelled.")
    if message.from_user is not None and session is not None:
        await admin_log.draft_cancelled(user=message.from_user, session=session, reason="Cancelled with /cancel")


@router.message(Command("post"))
@flags.chat_action(initial_sleep=1.0, action="upload_photo")
async def handle_post(message: Message, command: CommandObject, state: FSMContext, drafts: DraftWorkflow) -> None:
    user = message.from_user
    if user is None:
        await DraftState(state).clear()
        await message.answer("⚠️ This command is only available to user accounts.")
        return
    repository = await _parse_repository(message, command)
    if repository is None:
        return

    await drafts.create(message, DraftState(state), repository, owner=user)


@router.callback_query(
    DownloadDecisionCallback.filter(F.action == DownloadDecision.GENERATE),
    StateFilter(PostDraftState.awaiting_download_confirmation),
)
async def handle_generate_without_download(callback: CallbackQuery, state: FSMContext, drafts: DraftWorkflow) -> None:
    draft_state = DraftState(state)
    pending = await draft_state.pending_download()
    message = callback.message
    if pending is None or not isinstance(message, Message):
        await callback.answer("This confirmation is no longer active.", show_alert=True)
        return

    await callback.answer("Generating without a download source…")
    await message.edit_reply_markup(reply_markup=None)
    session = await drafts.create(
        message, draft_state, pending.repository, owner=callback.from_user, allow_missing_download=True
    )
    if session is not None:
        try:
            await message.delete()
        except TelegramAPIError:
            logger.debug("Download warning message remained after draft generation", exc_info=True)


@router.callback_query(
    DownloadDecisionCallback.filter(F.action == DownloadDecision.CANCEL),
    StateFilter(PostDraftState.awaiting_download_confirmation),
)
async def handle_cancel_without_download(callback: CallbackQuery, state: FSMContext) -> None:
    draft_state = DraftState(state)
    pending = await draft_state.pending_download()
    message = callback.message
    if pending is None or not isinstance(message, Message):
        await callback.answer("This confirmation is no longer active.", show_alert=True)
        return
    await draft_state.clear()
    await message.edit_reply_markup(reply_markup=None)
    await callback.answer("Post generation cancelled.")
    await message.answer("🗑️ Post generation cancelled.")


@router.callback_query(F.data.startswith(f"{DOWNLOAD_CALLBACK_PREFIX}:"))
async def handle_stale_download_confirmation(callback: CallbackQuery) -> None:
    await callback.answer("This confirmation is no longer active.", show_alert=True)


async def _parse_repository(message: Message, command: CommandObject) -> RepositoryRef | None:
    if not command.args:
        await message.answer(
            **as_list(
                Bold("Create a repository post"),
                "Send a public GitHub or GitLab repository URL:",
                Text(BotCommand("/post"), " https://github.com/owner/repository"),
            ).as_kwargs()
        )
        return None
    try:
        return parse_repository_url(command.args)
    except RepositoryUrlError as error:
        await message.answer(**as_list(Text("⚠️ ", Bold("Invalid repository URL")), str(error)).as_kwargs())
        return None


def parse_reconciliation(args: str | None) -> tuple[int, int | None, datetime | None] | None:
    match args.split() if args is not None else []:
        case [operation_text, action] if action.casefold() == "absent":
            operation_id = _positive_int(operation_text)
            return (operation_id, None, None) if operation_id is not None else None
        case [operation_text, message_text, published_text]:
            return _parse_visible_reconciliation(operation_text, message_text, published_text)
        case _:
            return None


def _parse_visible_reconciliation(
    operation_text: str, message_text: str, published_text: str
) -> tuple[int, int, datetime] | None:
    operation_id = _positive_int(operation_text)
    channel_message_id = _positive_int(message_text)
    try:
        published_at = datetime.fromisoformat(published_text)
    except ValueError:
        return None
    if operation_id is None or channel_message_id is None or published_at.utcoffset() is None:
        return None
    return operation_id, channel_message_id, published_at


def _positive_int(value: str) -> int | None:
    try:
        parsed = int(value)
    except ValueError:
        return None
    return parsed if parsed > 0 else None
