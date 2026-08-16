from typing import TYPE_CHECKING

import structlog
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, Message

from androidrepo_bot.posts.state import DraftSession, DraftState

if TYPE_CHECKING:
    from aiogram import Bot
    from aiogram.fsm.context import FSMContext

logger = structlog.get_logger(__name__)


def bound_bot(message: Message) -> Bot:
    bot = message.bot
    if bot is None:
        msg = "Telegram message is not bound to a bot"
        raise RuntimeError(msg)
    return bot


async def active_draft_context(callback: CallbackQuery, state: FSMContext) -> tuple[Message, DraftSession] | None:
    message = callback.message
    if not isinstance(message, Message):
        await reject_callback(callback)
        return None
    session = await DraftState(state).load()
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


async def deactivate_previous(message: Message, drafts: DraftState, bot: Bot) -> DraftSession | None:
    user = message.from_user
    if user is None:
        await drafts.clear()
        return None
    session = await drafts.load()
    if session is None:
        await drafts.clear()
        return None
    try:
        await bot.edit_message_reply_markup(chat_id=message.chat.id, message_id=session.message_id, reply_markup=None)
    except TelegramAPIError:
        logger.debug("Previous draft controls were unavailable", exc_info=True)
    await drafts.clear()
    return session
