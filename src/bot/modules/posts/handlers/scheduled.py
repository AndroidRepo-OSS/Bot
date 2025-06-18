# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from datetime import UTC, datetime

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from bot.database.operations import get_scheduled_posts_after_time

router = Router(name="scheduled_posts")


@router.message(Command("scheduled"))
async def list_scheduled_posts(message: Message) -> None:
    now = datetime.now(UTC)

    scheduled_posts = await get_scheduled_posts_after_time(now, now.replace(year=now.year + 1))

    if not scheduled_posts:
        await message.answer(
            "📅 <b>No Scheduled Posts</b>\n\nThere are no posts currently scheduled."
        )
        return

    unique_posts = {}
    for post in scheduled_posts:
        key = f"{post.id}_{post.repository_id}_{post.scheduled_time}"
        if key not in unique_posts:
            unique_posts[key] = post

    final_posts = list(unique_posts.values())

    text = "📅 <b>Scheduled Posts</b>\n\n"

    for i, post in enumerate(final_posts):
        status = "⏰ Pending" if not post.is_published else "✅ Published"
        text += (
            f"<b>ID:</b> {post.id}\n"
            f"<b>Repository:</b> {post.repository_full_name}\n"
            f"<b>Scheduled:</b> {post.scheduled_time.strftime('%Y-%m-%d %H:%M UTC')}\n"
            f"<b>Status:</b> {status}"
        )

        if i < len(final_posts) - 1:
            text += "\n" + "─" * 30 + "\n"

    await message.answer(text)
