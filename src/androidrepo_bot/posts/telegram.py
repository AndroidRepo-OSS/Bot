from typing import TYPE_CHECKING

import structlog
from aiogram.exceptions import TelegramAPIError
from aiogram.types import Message

from androidrepo_bot.posts.state import DraftState

if TYPE_CHECKING:
    from aiogram import Bot
    from aiogram.fsm.context import FSMContext
    from aiogram.types import CallbackQuery

    from androidrepo_bot.posts.state import DownloadConfirmation, DraftSession

logger = structlog.get_logger(__name__)


def bound_bot(message: Message) -> Bot:
    bot = message.bot
    if bot is None:
        msg = "Telegram message is not bound to a bot"
        raise RuntimeError(msg)
    return bot


async def active_draft(callback: CallbackQuery, state: FSMContext) -> dict[str, tuple[Message, DraftSession]] | bool:
    """Inject only a draft owned by this user and attached to this exact message."""
    message = callback.message
    if not isinstance(message, Message):
        return False
    session = await DraftState(state).load()
    if session is None or session.message_id != message.message_id or session.owner_user_id != callback.from_user.id:
        return False
    return {"draft_context": (message, session)}


async def pending_download(
    callback: CallbackQuery, state: FSMContext
) -> dict[str, Message | DownloadConfirmation] | bool:
    message = callback.message
    if not isinstance(message, Message):
        return False
    confirmation = await DraftState(state).pending_download()
    if (
        confirmation is None
        or confirmation.message_id != message.message_id
        or confirmation.owner_user_id != callback.from_user.id
    ):
        return False
    return {"message": message, "confirmation": confirmation}


async def delete_draft_messages(bot: Bot, chat_id: int, session: DraftSession) -> None:
    message_ids = [session.message_id]
    if session.notice_message_id is not None:
        message_ids.append(session.notice_message_id)
    try:
        # Telegram skips already deleted messages in a batch.
        await bot.delete_messages(chat_id=chat_id, message_ids=message_ids)
    except TelegramAPIError as error:
        logger.warning("Could not remove draft messages", error_type=type(error).__name__)


async def deactivate_previous(message: Message, drafts: DraftState, bot: Bot) -> DraftSession | None:
    session = await drafts.load()
    previous = session or await drafts.pending_download()
    await drafts.clear()
    if previous is None:
        return None
    try:
        await bot.edit_message_reply_markup(chat_id=message.chat.id, message_id=previous.message_id, reply_markup=None)
    except TelegramAPIError as error:
        logger.warning("Could not remove previous draft controls", error_type=type(error).__name__)
    return session
