from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

import structlog
from aiogram.exceptions import TelegramAPIError
from aiogram.filters.callback_data import CallbackData
from aiogram.types import BufferedInputFile, InputMediaPhoto
from aiogram.utils.formatting import Bold, HashTag, Italic, Pre, Text, TextLink, as_marked_section
from aiogram.utils.keyboard import InlineKeyboardBuilder

if TYPE_CHECKING:
    from aiogram.types import InlineKeyboardMarkup, Message

    from androidrepo_bot.media import BannerImage
    from androidrepo_bot.posts.models import PostDraft

TELEGRAM_CAPTION_LIMIT = 1_024
POST_CALLBACK_PREFIX = "post"
logger = structlog.get_logger(__name__)


class PostAction(StrEnum):
    PUBLISH = "publish"
    CONFIRM_PUBLISH = "confirm_publish"
    BACK = "back"
    REGENERATE = "regenerate"
    CANCEL = "cancel"


class PostCallback(CallbackData, prefix=POST_CALLBACK_PREFIX):
    action: PostAction


def draft_keyboard(draft: PostDraft) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📥 Download", url=draft.download_url)
    for text, action in (
        ("🚀 Publish", PostAction.PUBLISH),
        ("🔄 Regenerate", PostAction.REGENERATE),
        ("✖️ Cancel", PostAction.CANCEL),
    ):
        builder.button(text=text, callback_data=PostCallback(action=action))
    builder.adjust(1, 1, 2)
    return builder.as_markup()


def publish_confirmation_keyboard(draft: PostDraft) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📥 Download", url=draft.download_url)
    builder.button(text="✅ Publish now", callback_data=PostCallback(action=PostAction.CONFIRM_PUBLISH))
    builder.button(text="↩️ Back", callback_data=PostCallback(action=PostAction.BACK))
    builder.adjust(1, 1, 1)
    return builder.as_markup()


def published_post_keyboard(draft: PostDraft) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📥 Download", url=draft.download_url)
    return builder.as_markup()


class DraftProgress:
    def __init__(self, *, message: Message) -> None:
        self.message = message
        self.completed_steps = 0

    @classmethod
    async def start(cls, message: Message) -> DraftProgress:
        status = await message.answer(**_render_progress(completed_steps=0).as_kwargs())
        logger.debug(
            "Draft progress message created",
            progress_message_id=status.message_id,
            command_message_id=message.message_id,
        )
        return cls(message=status)

    async def complete_step(self) -> None:
        self.completed_steps += 1
        logger.debug(
            "Draft progress advanced", progress_message_id=self.message.message_id, completed_steps=self.completed_steps
        )
        await self._edit(_render_progress(completed_steps=self.completed_steps))

    async def fail(self, error_message: Text) -> None:
        logger.debug(
            "Draft progress marked failed",
            progress_message_id=self.message.message_id,
            completed_steps=self.completed_steps,
        )
        content = Text(_render_progress(completed_steps=self.completed_steps, failed=True), "\n\n", error_message)
        await self._edit(content)

    async def delete(self) -> None:
        try:
            await self.message.delete()
        except TelegramAPIError:
            logger.debug(
                "Draft preparation status message was already unavailable", progress_message_id=self.message.message_id
            )

    async def _edit(self, content: Text) -> None:
        try:
            await self.message.edit_text(**content.as_kwargs())
        except TelegramAPIError:
            logger.debug(
                "Could not update draft preparation status", progress_message_id=self.message.message_id, exc_info=True
            )


def _render_progress(*, completed_steps: int, failed: bool = False) -> Text:
    lines: list[str] = []
    steps = ("Repository", "Content", "Banner", "Telegram draft")
    for index, step in enumerate(steps):
        if index < completed_steps:
            marker = "✓"
        elif index == completed_steps:
            marker = "✗" if failed else ">"
        else:
            marker = " "
        lines.append(f"[{marker}] {step}")

    heading = "Draft preparation failed" if failed else "Preparing draft"
    return Text(Bold(heading), "\n", Pre("\n".join(lines)))


def render_post(draft: PostDraft) -> Text:
    features = as_marked_section(Text("✨ ", Bold("Key Features:")), *draft.features, marker="• ")
    links = as_marked_section(
        Text("🔗 ", Bold("Links:")), *(TextLink(link.label, url=link.url) for link in draft.links), marker="• "
    )
    tags = Text(
        "🏷️ ", *(Text(" ", HashTag(tag.value)) if index else HashTag(tag.value) for index, tag in enumerate(draft.tags))
    )

    content = Text(Bold(draft.title), "\n\n", Italic(draft.summary), "\n\n", features, "\n\n", links, "\n\n", tags)

    if len(content) > TELEGRAM_CAPTION_LIMIT:
        msg = "The generated post exceeds Telegram's caption limit"
        raise ValueError(msg)

    return content


def render_post_media(draft: PostDraft, banner: BannerImage) -> InputMediaPhoto:
    content = render_post(draft)
    return InputMediaPhoto(
        media=BufferedInputFile(banner.content, filename=banner.filename),
        **content.as_kwargs(text_key="caption", entities_key="caption_entities"),
    )
