from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

from aiogram.filters.callback_data import CallbackData
from aiogram.types import BufferedInputFile, InputMediaPhoto
from aiogram.utils.formatting import Bold, HashTag, Italic, Text, TextLink, as_list, as_marked_section
from aiogram.utils.keyboard import InlineKeyboardBuilder

if TYPE_CHECKING:
    from aiogram.types import InlineKeyboardMarkup

    from androidrepo_bot.generation.models import PostDraft
    from androidrepo_bot.media.models import BannerImage

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
    builder.adjust(1, 1)
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
    builder.adjust(*(1, 1, 1) if draft.download_url is not None else (1, 1))
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


def render_post_media(draft: PostDraft, banner: BannerImage) -> InputMediaPhoto:
    content = render_post(draft)
    return InputMediaPhoto(
        media=BufferedInputFile(banner.content, filename=banner.filename), **content.as_caption_kwargs()
    )
