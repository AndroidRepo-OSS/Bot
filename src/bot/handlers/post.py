# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

import re

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InaccessibleMessage,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from bot.config import Settings
from bot.states import PostStates
from bot.utils.github_client import GitHubClient
from bot.utils.models import AIGeneratedContent, GitHubRepository

router = Router(name="post")

GITHUB_URL_PATTERN = re.compile(r"^https?://github\.com/[\w.-]+/[\w.-]+/?$")

INVALID_URL_MESSAGE = (
    "❌ <b>Invalid Input</b>\n\n"
    "Please send a valid GitHub repository URL as text.\n\n"
    "<i>Example: https://github.com/user/repository</i>"
)

POST_CANCELLED_MESSAGE = (
    "❌ <b>Post Creation Cancelled</b>\n\n"
    "The post creation has been cancelled successfully.\n\n"
    "You can start again anytime with /post command."
)


@router.message(Command("post"))
async def post_command_handler(message: Message, state: FSMContext) -> None:
    await state.set_state(PostStates.waiting_for_github_url)

    await message.reply(
        "📱 <b>Android Repository Post Creator</b>\n\n"
        "Please send me the GitHub repository URL you want to create a post for.\n\n"
        "<i>Example: https://github.com/user/repository</i>\n\n"
        "💡 Use /cancel to cancel the post creation at any time."
    )


@router.message(Command("cancel"))
async def cancel_command_handler(message: Message, state: FSMContext) -> None:
    current_state = await state.get_state()

    if current_state is None:
        await message.reply(
            "❌ <b>No Active Post Creation</b>\n\n"
            "There's no post creation in progress to cancel.\n\n"
            "Use /post to start creating a new post."
        )
        return

    await state.clear()
    await message.reply(POST_CANCELLED_MESSAGE)


@router.message(PostStates.waiting_for_github_url, F.text)
async def github_url_handler(message: Message, state: FSMContext) -> None:
    if not message.text:
        await message.reply(INVALID_URL_MESSAGE)
        return

    url = message.text.strip()

    if not GITHUB_URL_PATTERN.match(url):
        await message.reply(
            "❌ <b>Invalid GitHub URL</b>\n\n"
            "Please provide a valid GitHub repository URL.\n\n"
            "<i>Example: https://github.com/user/repository</i>"
        )
        return

    await state.update_data(github_url=url)
    await state.set_state(PostStates.waiting_for_confirmation)

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Confirm", callback_data="confirm_post"),
                InlineKeyboardButton(text="❌ Cancel", callback_data="cancel_post"),
            ]
        ]
    )

    await message.reply(
        f"📋 <b>Post Preview</b>\n\n"
        f"<b>Repository:</b> <code>{url}</code>\n\n"
        f"Do you want to proceed with creating the post?",
        reply_markup=keyboard,
    )


@router.callback_query(F.data == "confirm_post")
async def confirm_post_handler(callback: CallbackQuery, state: FSMContext) -> None:
    if isinstance(callback.message, InaccessibleMessage):
        return

    data = await state.get_data()
    github_url = data.get("github_url")

    if not callback.message:
        return

    await callback.message.edit_text(
        f"🔄 <b>Processing Repository</b>\n\n"
        f"Fetching data from: <code>{github_url}</code>\n\n"
        f"<i>Please wait...</i>"
    )

    try:
        if not github_url:
            msg = "GitHub URL not found in state data"
            raise ValueError(msg)

        settings = Settings()  # type: ignore

        async with GitHubClient() as client:
            enhanced_data = await client.get_enhanced_repository_data(
                github_url,
                settings.openai_api_key.get_secret_value(),
                settings.openai_base_url,
            )

        repository = enhanced_data.repository
        ai_content = enhanced_data.ai_content

        post_text = _format_enhanced_post(repository, ai_content)

        await callback.message.edit_text(
            f"✅ <b>Repository Data Retrieved</b>\n\n"
            f"<b>Repository:</b> {repository.name}\n"
            f"<b>Author:</b> {repository.owner}\n\n"
            f"<i>Post generated successfully! Check the preview below.</i>"
        )

        preview_keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="❌ Cancel Post", callback_data="cancel_preview")]
            ]
        )

        await callback.message.answer(
            f"📋 <b>Post Preview</b>\n\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"{post_text}\n"
            f"━━━━━━━━━━━━━━━━\n\n"
            f"<i>This is how your post will look in the channel.</i>",
            reply_markup=preview_keyboard,
        )

    except Exception as e:
        await callback.message.edit_text(
            f"❌ <b>Error Processing Repository</b>\n\n"
            f"Failed to fetch data from: <code>{github_url}</code>\n\n"
            f"Error: <code>{e!s}</code>\n\n"
            f"Please try again or check if the repository is accessible."
        )

    await state.clear()
    await callback.answer("Repository processing completed!")


@router.callback_query(F.data == "cancel_post")
async def cancel_post_handler(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.message:
        return

    if isinstance(callback.message, InaccessibleMessage):
        return

    await callback.message.edit_text(
        "❌ <b>Post Creation Cancelled</b>\n\nYou can start again anytime with /post command."
    )

    await state.clear()
    await callback.answer("Post creation cancelled!")


@router.callback_query(F.data == "cancel_preview")
async def cancel_preview_handler(callback: CallbackQuery) -> None:
    if isinstance(callback.message, InaccessibleMessage):
        return

    if not callback.message:
        return

    await callback.message.edit_text(
        "❌ <b>Post Cancelled</b>\n\n"
        "The post preview has been cancelled.\n\n"
        "You can start again anytime with /post command."
    )

    await callback.answer("Post cancelled!")


@router.message(PostStates.waiting_for_github_url)
async def invalid_github_url_handler(message: Message) -> None:
    await message.reply(f"{INVALID_URL_MESSAGE}\n\n💡 Use /cancel to cancel the post creation.")


@router.message(Command("cancel"), PostStates.waiting_for_github_url)
async def cancel_during_url_input(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.reply(POST_CANCELLED_MESSAGE)


@router.message(Command("cancel"), PostStates.waiting_for_confirmation)
async def cancel_during_confirmation(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.reply(POST_CANCELLED_MESSAGE)


def _get_post_description(
    repository: GitHubRepository, ai_content: AIGeneratedContent | None
) -> str | None:
    return (
        ai_content.enhanced_description
        if ai_content and ai_content.enhanced_description
        else repository.description
    )


def _get_post_tags(
    repository: GitHubRepository, ai_content: AIGeneratedContent | None
) -> list[str]:
    return (
        ai_content.relevant_tags[:5]
        if ai_content and ai_content.relevant_tags
        else repository.topics[:5]
    )


def _format_enhanced_post(
    repository: GitHubRepository, ai_content: AIGeneratedContent | None
) -> str:
    description = _get_post_description(repository, ai_content)
    tags_to_show = _get_post_tags(repository, ai_content)

    post_text = f"<b>{repository.name}</b>\n\n"

    if description:
        post_text += f"<i>{description}</i>\n\n"

    if ai_content and ai_content.key_features:
        post_text += "<b>Key Features:</b>\n"
        for feature in ai_content.key_features:
            post_text += f"• {feature}\n"
        post_text += "\n"

    links = []

    links.append(f'• <a href="{repository.url}">GitHub Repository</a>')

    if ai_content and ai_content.important_links:
        additional_links = [
            f'• <a href="{link["url"]}">{link["title"]}</a>'
            for link in ai_content.important_links[:3]
        ]
        links.extend(additional_links)

    if links:
        post_text += "<b>Links:</b>\n"
        for link in links:
            post_text += f"{link}\n"
        post_text += "\n"

    post_text += f"<b>Author:</b> <code>{repository.owner}</code>\n"

    if tags_to_show:
        hashtags = " ".join(f"#{tag}" for tag in tags_to_show)
        post_text += f"<b>Tags:</b> {hashtags}\n"

    post_text += "<b>Follow:</b> @AndroidRepo // <b>Join:</b> @AndroidRepo_chat"

    return post_text
