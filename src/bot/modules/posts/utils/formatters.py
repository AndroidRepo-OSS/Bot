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
        available_tags = ai_content.relevant_tags
    else:
        available_tags = repository.topics

    return available_tags or []


def format_enhanced_post(repository: Repository, ai_content: AIGeneratedContent | None) -> str:
    post_sections = []

    title_section = _format_title_section(repository, ai_content)
    post_sections.append(title_section)

    description_section = _format_description_section(repository, ai_content)
    if description_section:
        post_sections.append(description_section)

    features_section = _format_features_section(ai_content)
    if features_section:
        post_sections.append(features_section)

    links_section = _format_links_section(repository, ai_content)
    post_sections.append(links_section)

    tags_section = _format_tags_section(repository, ai_content)
    if tags_section:
        post_sections.append(tags_section)

    return "\n\n".join(post_sections)


def _format_title_section(repository: Repository, ai_content: AIGeneratedContent | None) -> str:
    project_name = get_project_name(repository, ai_content)
    return f"<b>{project_name}</b>"


def _format_description_section(
    repository: Repository, ai_content: AIGeneratedContent | None
) -> str:
    if ai_content and ai_content.enhanced_description:
        description = ai_content.enhanced_description
    else:
        description = repository.description or ""

    return f"<i>{description}</i>" if description else ""


def _format_features_section(ai_content: AIGeneratedContent | None) -> str:
    if not ai_content or not ai_content.key_features:
        return ""

    feature_items = "\n".join(f"• {feature}" for feature in ai_content.key_features)
    return f"✨ <b>Key Features:</b>\n{feature_items}"


def _format_links_section(repository: Repository, ai_content: AIGeneratedContent | None) -> str:
    platform_name = _get_platform_name(repository)

    link_items = [f'• <a href="{repository.url}">{platform_name} Repository</a>']

    if ai_content and ai_content.important_links:
        additional_link_items = [
            f'• <a href="{link.url}">{link.title}</a>' for link in ai_content.important_links
        ]
        link_items.extend(additional_link_items)

    links_text = "\n".join(link_items)
    return f"🔗 <b>Links:</b>\n{links_text}"


def _get_platform_name(repository: Repository) -> str:
    return "GitHub" if isinstance(repository, GitHubRepository) else "GitLab"


def _format_tags_section(repository: Repository, ai_content: AIGeneratedContent | None) -> str:
    available_tags = _get_tags_for_post(repository, ai_content)
    if not available_tags:
        return ""

    hashtags = " ".join(f"#{tag}" for tag in available_tags)
    return f"🏷️ <b>Tags:</b> {hashtags}"


def _get_tags_for_post(repository: Repository, ai_content: AIGeneratedContent | None) -> list[str]:
    if ai_content and ai_content.relevant_tags:
        available_tags = ai_content.relevant_tags
    else:
        available_tags = repository.topics

    return available_tags or []
