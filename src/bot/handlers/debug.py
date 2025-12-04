# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations

from typing import TYPE_CHECKING

from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.utils.formatting import Bold, Text, TextLink, as_key_value, as_list

from bot.utils.deeplinks import extract_submission_id

if TYPE_CHECKING:
    from aiogram.filters.command import CommandObject
    from aiogram.types import Message

    from bot.integrations.repositories import RepositoryAuthor, RepositoryReadme
    from bot.services import PreviewDebugRegistry
    from bot.services.preview_registry import PreviewDebugEntry

    type TextNode = str | Text

router = Router(name="preview-debug")


@router.message(CommandStart(deep_link=True, deep_link_encoded=True))
async def handle_preview_debug_link(
    message: Message, command: CommandObject, preview_registry: PreviewDebugRegistry
) -> None:
    submission_id = extract_submission_id(command.args or "")
    if not submission_id:
        await message.answer("This debug link is invalid or expired.")
        return

    preview_entry = preview_registry.get(submission_id)
    if preview_entry is None:
        await message.answer("No preview data found. It may have expired after publishing/cancelling.")
        return

    content = _render_repository(submission_id, preview_entry)
    await message.answer(**content.as_kwargs(), disable_web_page_preview=True)


def _format_author(author: RepositoryAuthor) -> TextNode:
    label = author.display_name or author.username
    display = f"{label} (@{author.username})" if label != author.username else author.username

    if author.url:
        return TextLink(display, url=str(author.url))
    return display


def _format_readme(readme: RepositoryReadme | None) -> Text:
    if readme is None:
        return Text("Not available")

    path_node: TextNode = TextLink(readme.path, url=str(readme.source_url)) if readme.source_url else readme.path
    return Text(path_node, f" ({len(readme.content)} chars)")


def _render_repository(submission_id: str, entry: PreviewDebugEntry) -> Text:
    repository = entry.repository
    rows: list[Text | str] = [
        Bold("Repository Data"),
        "",
        as_key_value("Submission ID", submission_id),
        as_key_value("Name", TextLink(repository.full_name, url=str(repository.web_url))),
        as_key_value("Platform", repository.platform.value.title()),
        as_key_value("ID", str(repository.id)),
        as_key_value("Author", _format_author(repository.author)),
        as_key_value("Description", repository.description or "—"),
        as_key_value("Tags", ", ".join(repository.tags) if repository.tags else "—"),
        as_key_value("README", _format_readme(repository.readme)),
    ]

    if entry.summary_model:
        rows.append(as_key_value("LLM (summary)", entry.summary_model))
    if entry.revision_model:
        rows.append(as_key_value("LLM (revision)", entry.revision_model))

    return as_list(*rows)
