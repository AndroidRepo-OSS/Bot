# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, InaccessibleMessage

from bot.config import Settings
from bot.database import submit_app
from bot.modules.posts.callbacks import PostAction, PostCallback
from bot.modules.posts.utils import get_project_name, try_edit_message

router = Router(name="publish_post")


@router.callback_query(PostCallback.filter(F.action == PostAction.PUBLISH))
async def publish_post_handler(
    callback: CallbackQuery, state: FSMContext, callback_data: PostCallback
) -> None:
    if (
        isinstance(callback.message, InaccessibleMessage)
        or not callback.bot
        or not callback.message
    ):
        return

    data = await state.get_data()
    post_text, enhanced_data, banner_buffer = (
        data.get("post_text"),
        data.get("enhanced_data"),
        data.get("banner_buffer"),
    )

    if not post_text or not enhanced_data:
        return

    if not banner_buffer:
        error_text = (
            "❌ <b>Banner Required</b>\n\n"
            "Cannot publish without a banner.\n\n"
            "💡 Try regenerating the post to create a new banner."
        )
        await try_edit_message(callback.message, error_text)
        return

    settings = Settings()  # type: ignore

    try:
        repository = enhanced_data.repository
        project_name = get_project_name(repository, enhanced_data.ai_content)
        banner_input = BufferedInputFile(
            banner_buffer.getvalue(),
            filename=f"{project_name.lower().replace(' ', '_')}_banner.png",
        )

        sent_message = await callback.bot.send_photo(
            chat_id=settings.channel_id, photo=banner_input, caption=post_text
        )

        await submit_app(repository, sent_message.message_id)

        banner_buffer.close()

        success_text = (
            "✅ <b>Post Published Successfully!</b>\n\n"
            f"<b>Project:</b> {project_name}\n"
            f"<b>Repository:</b> {repository.name}\n"
            f"<b>Author:</b> {repository.owner}\n\n"
            "<i>Post sent to channel and saved to database.</i>"
        )
        await try_edit_message(callback.message, success_text)

    except Exception as e:
        project_name = get_project_name(enhanced_data.repository, enhanced_data.ai_content)
        error_text = (
            "❌ <b>Publishing Failed</b>\n\n"
            f"<b>Project:</b> {project_name}\n"
            f"<b>Repository:</b> {enhanced_data.repository.name}\n"
            f"<b>Author:</b> {enhanced_data.repository.owner}\n\n"
            f"<b>Error:</b> {e!s}\n\n"
            "<i>Check channel ID and bot permissions.</i>"
        )
        await try_edit_message(callback.message, error_text)

    await state.clear()
