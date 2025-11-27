# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations

from typing import TYPE_CHECKING

from aiogram import Router, flags
from aiogram.filters import CommandStart
from aiogram.utils.formatting import Bold, Text, TextLink

from bot.utils.deeplinks import extract_submission_id

if TYPE_CHECKING:
    from aiogram.filters.command import CommandObject
    from aiogram.types import Message

    from bot.container import BotDependencies
    from bot.integrations.repositories import RepositoryInfo

router = Router(name="preview-debug")


@router.message(CommandStart(deep_link=True, deep_link_encoded=True))
@flags.chat_action(initial_sleep=0.0)
async def handle_preview_debug_link(
    message: Message, command: CommandObject, bot_dependencies: BotDependencies
) -> None:
    submission_id = extract_submission_id(command.args or "")
    if not submission_id:
        await message.answer("This debug link is invalid or expired.")
        return

    repository = bot_dependencies.preview_registry.get(submission_id)
    if repository is None:
        await message.answer("No preview data found. It may have expired after publishing/cancelling.")
        return

    content = _render_repository(submission_id, repository)
    await message.answer(content, disable_web_page_preview=True)


def _render_repository(submission_id: str, repository: RepositoryInfo) -> str:

    author_label = repository.author.display_name or repository.author.username
    author_compound = (
        f"{author_label} (@{repository.author.username})"
        if author_label and author_label != repository.author.username
        else repository.author.username
    )
    if repository.author.url:
        author_repr: str | Text = TextLink(author_compound, url=str(repository.author.url))
    else:
        author_repr = author_compound

    readme_repr: list[str | Text]
    if repository.readme:
        readme_repr = []
        if repository.readme.source_url:
            readme_repr.append(TextLink(repository.readme.path, url=str(repository.readme.source_url)))
        else:
            readme_repr.append(repository.readme.path)
        readme_repr.append(f" ({len(repository.readme.content)} chars)")
    else:
        readme_repr = ["Not available"]

    tags = ", ".join(repository.tags) if repository.tags else "—"
    description = repository.description or "—"

    parts: list[str | Text] = [
        Bold("Repository Data"),
        "\n\n",
        Bold("Submission ID"),
        ": ",
        submission_id,
        "\n",
        Bold("Name"),
        ": ",
        TextLink(repository.full_name, url=str(repository.web_url)),
        "\n",
        Bold("Platform"),
        ": ",
        repository.platform.value.title(),
        "\n",
        Bold("ID"),
        ": ",
        str(repository.id),
        "\n",
        Bold("Author"),
        ": ",
        author_repr,
        "\n",
        Bold("Description"),
        ": ",
        description,
        "\n",
        Bold("Tags"),
        ": ",
        tags,
        "\n",
        Bold("README"),
        ": ",
        *readme_repr,
    ]

    return Text(*parts).as_html()
