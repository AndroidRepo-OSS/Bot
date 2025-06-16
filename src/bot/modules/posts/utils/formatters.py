# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from bot.modules.posts.callbacks import EditField
from bot.utils.models import AIGeneratedContent, GitHubRepository, GitLabRepository

Repository = GitHubRepository | GitLabRepository


def get_field_name(field: EditField) -> str:
    field_names = {
        EditField.DESCRIPTION: "description",
        EditField.TAGS: "tags",
        EditField.FEATURES: "features",
        EditField.LINKS: "links",
    }
    return field_names.get(field, "unknown")


def get_project_name(repository: Repository, ai_content: AIGeneratedContent | None) -> str:
    if ai_content and ai_content.project_name:
        return ai_content.project_name
    return repository.name


def get_post_description(
    repository: Repository, ai_content: AIGeneratedContent | None
) -> str | None:
    if ai_content and ai_content.enhanced_description:
        return ai_content.enhanced_description
    return repository.description


def get_post_tags(repository: Repository, ai_content: AIGeneratedContent | None) -> list[str]:
    if ai_content and ai_content.relevant_tags:
        tags = ai_content.relevant_tags
    else:
        tags = repository.topics

    return tags[:7] if tags else []


def format_enhanced_post(repository: Repository, ai_content: AIGeneratedContent | None) -> str:
    post_parts = []

    project_name = get_project_name(repository, ai_content)
    post_parts.append(f"<b>{project_name}</b>")

    description = _get_description_for_post(repository, ai_content)
    if description:
        post_parts.append(f"<i>{description}</i>")

    features_section = _format_features_section(ai_content)
    if features_section:
        post_parts.append(features_section)

    links_section = _format_links_section(repository, ai_content)
    post_parts.append(links_section)

    author_section = _format_author_section(repository, ai_content)
    post_parts.append(author_section)

    return "\n\n".join(post_parts)


def _get_description_for_post(
    repository: Repository, ai_content: AIGeneratedContent | None
) -> str:
    if ai_content and ai_content.enhanced_description:
        return ai_content.enhanced_description
    return repository.description or ""


def _format_features_section(ai_content: AIGeneratedContent | None) -> str:
    if not ai_content or not ai_content.key_features:
        return ""

    feature_list = "\n".join(f"• {feature}" for feature in ai_content.key_features)
    return f"✨ <b>Key Features:</b>\n{feature_list}"


def _format_links_section(repository: Repository, ai_content: AIGeneratedContent | None) -> str:
    platform_name = "GitHub" if isinstance(repository, GitHubRepository) else "GitLab"

    link_items = [f'• <a href="{repository.url}">{platform_name} Repository</a>']

    if ai_content and ai_content.important_links:
        additional_links = ai_content.important_links[:3]
        link_items.extend(f'• <a href="{link.url}">{link.title}</a>' for link in additional_links)

    links_text = "\n".join(link_items)
    return f"🔗 <b>Links:</b>\n{links_text}"


def _format_author_section(repository: Repository, ai_content: AIGeneratedContent | None) -> str:
    author_line = f"👤 <b>Author:</b> <code>{repository.owner}</code>"

    tags = _get_tags_for_post(repository, ai_content)
    if tags:
        hashtags = " ".join(f"#{tag}" for tag in tags)
        tags_line = f"🏷️ <b>Tags:</b> {hashtags}"
        return f"{author_line}\n{tags_line}"

    return author_line


def _get_tags_for_post(repository: Repository, ai_content: AIGeneratedContent | None) -> list[str]:
    if ai_content and ai_content.relevant_tags:
        tags = ai_content.relevant_tags
    else:
        tags = repository.topics

    return tags[:5] if tags else []
