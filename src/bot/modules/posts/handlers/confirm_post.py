# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

import asyncio
from datetime import UTC, datetime
from io import BytesIO

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, InaccessibleMessage, Message

from bot.config import Settings
from bot.database import can_submit_app
from bot.modules.posts.callbacks import PostAction, PostCallback
from bot.modules.posts.utils import (
    PostStates,
    format_enhanced_post,
    get_project_name,
    try_edit_message,
)
from bot.modules.posts.utils.keyboards import create_keyboard
from bot.modules.posts.utils.models import KeyboardType
from bot.utils.banner_generator import generate_banner
from bot.utils.repository_client import RepositoryClient

router = Router(name="confirm_post")


def validate_and_parse_url(repository_url: str) -> tuple[str, str]:
    url_parts = repository_url.rstrip("/").split("/")
    if len(url_parts) < 2:
        msg = "Invalid repository URL format"
        raise ValueError(msg)
    return url_parts[-2], url_parts[-1]


@router.callback_query(PostCallback.filter(F.action == PostAction.CONFIRM))
async def confirm_post_handler(
    callback: CallbackQuery, state: FSMContext, callback_data: PostCallback
) -> None:
    if isinstance(callback.message, InaccessibleMessage) or not callback.message:
        return

    data = await state.get_data()
    repository_url = data.get("repository_url")
    if not repository_url:
        return

    try:
        owner, repo_name = validate_and_parse_url(repository_url)
    except ValueError:
        await try_edit_message(
            callback.message,
            "❌ <b>Invalid Repository URL</b>\n\n"
            "Please provide a valid repository URL and try again with /post",
        )
        await state.clear()
        return

    await process_repository_submission(callback.message, state, repository_url, owner, repo_name)


async def process_repository_submission(
    message: Message, state: FSMContext, repository_url: str, owner: str, repo_name: str
) -> None:
    await try_edit_message(
        message,
        f"🔄 <b>Validating Repository</b>\n\n"
        f"<b>Repository:</b> {repo_name}\n"
        f"<b>Author:</b> {owner}\n\n"
        f"<i>Checking posting eligibility...</i>",
    )

    try:
        async with RepositoryClient() as client:
            if not client.is_valid_repository_url(repository_url):
                await try_edit_message(
                    message,
                    f"❌ <b>Invalid Repository</b>\n\n"
                    f"<b>Repository:</b> {repo_name}\n"
                    f"<b>URL:</b> <code>{repository_url}</code>\n\n"
                    "Please check the URL and try again with /post",
                )
                await state.clear()
                return

            repository_data = await client.get_basic_repository_data(repository_url)
            can_submit, last_submission_date = await can_submit_app(repository_data.id)

            if not can_submit and last_submission_date:
                await handle_repost_restriction(
                    message, state, repo_name, owner, last_submission_date
                )
                return

            await try_edit_message(
                message,
                f"🤖 <b>Generating AI Content</b>\n\n"
                f"<b>Repository:</b> {repo_name}\n"
                f"<b>Author:</b> {owner}\n\n"
                f"<i>Creating enhanced content...</i>",
            )

            settings = Settings()  # type: ignore
            enhanced_data = await client.get_enhanced_repository_data(
                repository_url,
                settings.openai_api_key.get_secret_value(),
                openai_base_url=settings.openai_base_url,
            )

            await process_post_content(message, state, enhanced_data)

    except Exception as e:
        await handle_processing_error(message, state, repository_url, str(e))


async def handle_repost_restriction(
    message: Message, state: FSMContext, repo_name: str, owner: str, last_submission_date: datetime
) -> None:
    if last_submission_date.tzinfo is None:
        last_submission_date = last_submission_date.replace(tzinfo=UTC)

    days_since_last = (datetime.now(tz=UTC) - last_submission_date).days
    remaining_days = 90 - days_since_last

    await try_edit_message(
        message,
        f"🚫 <b>Repost Not Allowed</b>\n\n"
        f"<b>Repository:</b> {repo_name}\n"
        f"<b>Author:</b> {owner}\n\n"
        f"Posted <b>{days_since_last} days ago</b>\n"
        f"Wait <b>{remaining_days} more days</b> to repost\n\n"
        f"<i>3-month cooldown prevents spam</i>",
    )
    await state.clear()


async def process_post_content(message: Message, state: FSMContext, enhanced_data) -> None:
    repository = enhanced_data.repository
    ai_content = enhanced_data.ai_content

    await try_edit_message(
        message,
        f"🎨 <b>Finalizing Content</b>\n\n"
        f"<b>Repository:</b> {repository.name}\n"
        f"<b>Author:</b> {repository.owner}\n\n"
        f"<i>Formatting post and generating banner...</i>",
    )

    post_text_task = asyncio.create_task(
        asyncio.to_thread(format_enhanced_post, repository, ai_content)
    )

    project_name = get_project_name(repository, ai_content)
    banner_task = asyncio.create_task(asyncio.to_thread(generate_banner, project_name))

    try:
        post_text, banner_buffer = await asyncio.gather(
            post_text_task, banner_task, return_exceptions=True
        )

        if isinstance(post_text, Exception):
            raise post_text
        if isinstance(banner_buffer, Exception):
            banner_generated = False
            banner_buffer = None
        else:
            banner_generated = True

    except Exception:
        await handle_content_generation_error(message, state, project_name)
        return

    await finalize_post_preview(
        message, state, enhanced_data, str(post_text), banner_buffer, banner_generated
    )


async def finalize_post_preview(
    message: Message,
    state: FSMContext,
    enhanced_data,
    post_text: str,
    banner_buffer,
    banner_generated: bool,
) -> None:
    await state.update_data(
        enhanced_data=enhanced_data,
        post_text=post_text,
        banner_buffer=banner_buffer if banner_generated else None,
        banner_generated=banner_generated,
    )
    await state.set_state(PostStates.previewing_post)

    repository = enhanced_data.repository
    banner_status = "✅ Ready" if banner_generated else "❌ Failed"

    if banner_generated and banner_buffer:
        await send_successful_preview(message, banner_buffer, post_text, repository, banner_status)
    else:
        await handle_banner_generation_failure(message, state, repository)


async def send_successful_preview(
    message: Message, banner_buffer: BytesIO, post_text: str, repository, banner_status: str
) -> None:
    preview_header = (
        f"✅ <b>Post Ready</b>\n\n"
        f"<b>Repository:</b> {repository.name}\n"
        f"<b>Author:</b> {repository.owner}\n"
        f"<b>Banner:</b> {banner_status}\n\n"
        f"<i>Review and publish when ready</i>"
    )

    banner_input = BufferedInputFile(banner_buffer.getvalue(), filename="banner.png")

    if message.photo:
        await message.delete()
        await message.answer(preview_header)
        await message.answer_photo(
            photo=banner_input,
            caption=post_text,
            reply_markup=create_keyboard(KeyboardType.PREVIEW),
        )
    else:
        await try_edit_message(message, preview_header)
        await message.answer_photo(
            photo=banner_input,
            caption=post_text,
            reply_markup=create_keyboard(KeyboardType.PREVIEW),
        )


async def handle_banner_generation_failure(
    message: Message, state: FSMContext, repository
) -> None:
    await try_edit_message(
        message,
        f"❌ <b>Banner Generation Failed</b>\n\n"
        f"<b>Repository:</b> {repository.name}\n"
        f"<b>Author:</b> {repository.owner}\n\n"
        f"<b>Solutions:</b>\n"
        f"• Retry with /post\n"
        f"• Check repository name\n\n"
        f"<i>Banner required for publishing</i>",
    )
    await state.clear()


async def handle_content_generation_error(
    message: Message, state: FSMContext, project_name: str
) -> None:
    await try_edit_message(
        message,
        f"❌ <b>Content Generation Error</b>\n\n"
        f"<b>Project:</b> {project_name}\n\n"
        f"<b>Solutions:</b>\n"
        f"• Try /post again\n"
        f"• Check repository validity\n\n"
        f"<i>Banner required for channel publishing</i>",
    )
    await state.clear()


async def handle_processing_error(
    message: Message, state: FSMContext, repository_url: str, error: str
) -> None:
    await try_edit_message(
        message,
        f"❌ <b>Processing Failed</b>\n\n"
        f"<b>URL:</b> <code>{repository_url[:50]}...</code>\n\n"
        f"<b>Error:</b> <code>{error[:100]}...</code>\n\n"
        f"💡 Try /post again or check URL",
    )
    await state.clear()
