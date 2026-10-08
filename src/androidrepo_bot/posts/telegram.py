from enum import StrEnum
from typing import TYPE_CHECKING

import structlog
from aiogram.exceptions import TelegramAPIError
from aiogram.filters.callback_data import CallbackData
from aiogram.types import BufferedInputFile, Message
from aiogram.utils.formatting import Bold, HashTag, Italic, Text, TextLink, as_list, as_marked_section
from aiogram.utils.keyboard import InlineKeyboardBuilder

from androidrepo_bot.posts.state import DraftState

if TYPE_CHECKING:
    from aiogram import Bot
    from aiogram.fsm.context import FSMContext
    from aiogram.types import CallbackQuery, InlineKeyboardMarkup

    from androidrepo_bot.generation.models import PostDraft
    from androidrepo_bot.media.models import BannerImage
    from androidrepo_bot.posts.state import DownloadConfirmation, DraftSession

type DraftContext = tuple[Message, DraftSession, DraftState]

logger = structlog.get_logger(__name__)


async def active_draft(callback: CallbackQuery, state: FSMContext) -> dict[str, DraftContext] | bool:
    """Inject only a draft owned by this user and attached to this exact message."""
    message = callback.message
    if not isinstance(message, Message):
        return False
    draft_state = DraftState(state)
    session = await draft_state.load()
    if session is None or session.message_id != message.message_id or session.owner_user_id != callback.from_user.id:
        return False
    return {"draft_context": (message, session, draft_state)}


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


TELEGRAM_CAPTION_LIMIT = 1_024
POST_CALLBACK_PREFIX = "post"
DOWNLOAD_CALLBACK_PREFIX = "download_confirmation"


class PostAction(StrEnum):
    PUBLISH = "publish"
    CONFIRM_PUBLISH = "confirm_publish"
    BACK = "back"
    REGENERATE = "regenerate"
    CANCEL = "cancel"


class PostCallback(CallbackData, prefix=POST_CALLBACK_PREFIX):
    action: PostAction


class DownloadDecision(StrEnum):
    GENERATE = "generate"
    CANCEL = "cancel"


class DownloadDecisionCallback(CallbackData, prefix=DOWNLOAD_CALLBACK_PREFIX):
    action: DownloadDecision


def missing_download_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="Generate without download", callback_data=DownloadDecisionCallback(action=DownloadDecision.GENERATE)
    )
    builder.button(text="Cancel", callback_data=DownloadDecisionCallback(action=DownloadDecision.CANCEL))
    builder.adjust(1)
    return builder.as_markup()


def draft_keyboard(draft: PostDraft) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if draft.download_url is not None:
        builder.button(text="📥 Download", url=draft.download_url)
    for text, action in (
        ("🚀 Publish", PostAction.PUBLISH),
        ("🔄 Regenerate", PostAction.REGENERATE),
        ("✖️ Cancel", PostAction.CANCEL),
    ):
        builder.button(text=text, callback_data=PostCallback(action=action))
    builder.adjust(*(1, 1, 2) if draft.download_url is not None else (1, 2))
    return builder.as_markup()


def publish_confirmation_keyboard(draft: PostDraft) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if draft.download_url is not None:
        builder.button(text="📥 Download", url=draft.download_url)
    builder.button(text="✅ Publish now", callback_data=PostCallback(action=PostAction.CONFIRM_PUBLISH))
    builder.button(text="↩️ Back", callback_data=PostCallback(action=PostAction.BACK))
    builder.adjust(1)
    return builder.as_markup()


def published_post_keyboard(draft: PostDraft) -> InlineKeyboardMarkup | None:
    if draft.download_url is None:
        return None
    builder = InlineKeyboardBuilder()
    builder.button(text="📥 Download", url=draft.download_url)
    return builder.as_markup()


def render_post(draft: PostDraft) -> Text:
    features = as_marked_section(Text("✨ ", Bold("Key Features:")), *draft.features, marker="• ")
    links = as_marked_section(
        Text("🔗 ", Bold("Links:")), *(TextLink(link.label, url=link.url) for link in draft.links), marker="• "
    )
    tags = Text("🏷️ ", as_list(*(HashTag(tag.value) for tag in draft.tags), sep=" "))
    content = as_list(Bold(draft.title), Italic(draft.summary), features, links, tags, sep="\n\n")

    if len(content) > TELEGRAM_CAPTION_LIMIT:
        msg = "The generated post exceeds Telegram's caption limit"
        raise ValueError(msg)

    return content


async def send_draft(message: Message, draft: PostDraft, banner: BannerImage) -> Message:
    return await message.answer_photo(
        photo=BufferedInputFile(banner.content, filename=banner.filename),
        **render_post(draft).as_caption_kwargs(),
        reply_markup=draft_keyboard(draft),
    )


SOURCE_CODE_URL = "https://github.com/AndroidRepo-OSS/Bot"
CHANNEL_URL = "https://t.me/AndroidRepo"
COMMUNITY_URL = "https://t.me/AndroidRepo_chat"


def start_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="💻 Source code", url=SOURCE_CODE_URL)
    builder.button(text="📢 Channel", url=CHANNEL_URL)
    builder.button(text="💬 Community", url=COMMUNITY_URL)
    builder.adjust(1, 2)
    return builder.as_markup()
