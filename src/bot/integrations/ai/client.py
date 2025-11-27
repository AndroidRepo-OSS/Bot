# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from pydantic_ai import Agent
from pydantic_ai.models.fallback import FallbackModel
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.settings import ModelSettings

from .errors import PreviewEditError, RepositorySummaryError
from .models import RepositorySummary, RepositorySummaryDependencies, RepositorySummaryRevisionDependencies

if TYPE_CHECKING:
    from pydantic_ai import RunContext

    from bot.integrations.repositories.models import RepositoryInfo

_URL_PATTERN = re.compile(r"https?://[^\s)]+", re.IGNORECASE)
_MAX_README_CHARS = 16000

_SYSTEM_INSTRUCTIONS = """\
You are an assistant that creates concise summaries of Android open-source projects \
for sharing in a developer community Telegram channel.

## Task
Analyze the repository metadata and generate a structured summary that helps other \
developers and Android enthusiasts understand what the project does and whether it \
might be useful to them.

## Output Guidelines
- Write in a clear, informative tone aimed at developers and tech-savvy users
- Focus on WHAT the project does and WHO it's for
- Keep enhanced_description between 150-280 characters (2-3 sentences)
- Select 3-4 key features that best describe the project's capabilities
- Be factual and objective — avoid promotional language

## Key Features Format
Each feature should:
- Clearly describe a capability or characteristic
- Be concise (under 60 characters)
- Use technical terms approprgiiately when relevant

## Important Links Selection
- Include useful links: releases, app stores, documentation, project website
- Exclude the main repository URL (already provided separately)
- Use clear labels like "F-Droid", "Google Play", "Documentation", "Website", etc.
- Select a maximum of 4 important links
- NEVER include links to Telegram channels, groups, or any Telegram URLs
- NEVER include links to other social media or messaging apps (Discord, Twitter, etc.)
- NEVER include license file links (e.g., LICENSE, LICENSE.md, COPYING)

## Constraints
- Total response must stay under 4000 characters when rendered
- Only include information present in the source material
- If information is unclear or missing, omit rather than guess"""

_EDIT_SYSTEM_INSTRUCTIONS = """\
You update previously generated Android project previews based on short human edit requests.

## Task
Use the existing summary as a baseline and adjust only the parts requested. Keep the tone
informative and developer-friendly. When the user asks for additions, rewording, or removals,
apply them precisely without inventing new facts.

## Guidelines
- Preserve repository facts unless the user explicitly corrects them
- Maintain concise enhanced_description (2-3 sentences, max ~280 chars)
- Keep 3-4 key features max; drop or replace ones the user dislikes
- Never introduce new URLs beyond those already available
- If the request is unclear, make the smallest reasonable change that satisfies it

Return the full structured summary every time."""


class RepositorySummaryAgent:
    __slots__ = ("_edit_agent", "_summary_agent")

    def __init__(self, *, api_key: str, base_url: str | None = None) -> None:
        provider = OpenAIProvider(api_key=api_key, base_url=base_url)

        primary_model = OpenAIChatModel("openai/gpt-4.1", provider=provider)
        fallback_model = OpenAIChatModel("openai/gpt-4.1-mini", provider=provider)
        model = FallbackModel(primary_model, fallback_model)

        model_settings = ModelSettings(temperature=0.25, frequency_penalty=0.2, presence_penalty=0.0, max_tokens=4000)

        self._summary_agent: Agent[RepositorySummaryDependencies, RepositorySummary] = Agent(
            model=model,
            output_type=RepositorySummary,
            deps_type=RepositorySummaryDependencies,
            instructions=_SYSTEM_INSTRUCTIONS,
            retries=2,
            model_settings=model_settings,
        )
        self._register_summary_instructions()

        self._edit_agent: Agent[RepositorySummaryRevisionDependencies, RepositorySummary] = Agent(
            model=model,
            output_type=RepositorySummary,
            deps_type=RepositorySummaryRevisionDependencies,
            instructions=_EDIT_SYSTEM_INSTRUCTIONS,
            retries=2,
            model_settings=model_settings,
        )
        self._register_edit_instructions()

    def _register_summary_instructions(self) -> None:
        @self._summary_agent.instructions
        def provide_repository_context(ctx: RunContext[RepositorySummaryDependencies]) -> str:
            repo = ctx.deps.repository
            parts = [
                "## Repository Data",
                "",
                f"**Name:** {repo.name}",
                f"**Full Name:** {repo.full_name}",
                f"**Author:** {repo.author.display_name or repo.author.username}",
                f"**Platform:** {repo.platform.value}",
                f"**Description:** {repo.description or 'Not provided'}",
            ]

            if repo.tags:
                parts.append(f"**Tags:** {', '.join(repo.tags)}")

            parts.append(f"**Repository URL:** {repo.web_url}")

            if ctx.deps.links:
                parts.extend(["", "## Available Links (select relevant ones)"])
                parts.extend(f"- {link}" for link in ctx.deps.links)

            if ctx.deps.readme_excerpt:
                parts.extend([
                    "",
                    "## README Content",
                    "Use this to extract features, benefits, and additional context:",
                    "",
                    ctx.deps.readme_excerpt,
                ])

            return "\n".join(parts)

    async def summarize(self, repository: RepositoryInfo) -> RepositorySummary:
        deps = _build_dependencies(repository)

        try:
            result = await self._summary_agent.run(
                "Generate a marketing summary for this Android repository. "
                "Extract the project name, write a compelling description, "
                "identify key features, and select relevant links.",
                deps=deps,
            )
        except Exception as exc:
            raise RepositorySummaryError(original_error=exc) from exc

        return result.output

    def _register_edit_instructions(self) -> None:
        @self._edit_agent.instructions
        def provide_revision_context(ctx: RunContext[RepositorySummaryRevisionDependencies]) -> str:
            repo = ctx.deps.repository
            summary = ctx.deps.current_summary
            parts = [
                "## Repository Data",
                "",
                f"**Name:** {repo.name}",
                f"**Full Name:** {repo.full_name}",
                f"**Platform:** {repo.platform.value}",
                f"**Description:** {repo.description or 'Not provided'}",
                "",
                "## Current Preview",
                f"**Project Name:** {summary.project_name}",
                f"**Enhanced Description:** {summary.enhanced_description}",
                "**Key Features:**",
            ]

            if summary.key_features:
                parts.extend(f"- {feature}" for feature in summary.key_features)
            else:
                parts.append("- (none provided)")

            parts.extend(["", "**Important Links:**"])
            if summary.important_links:
                parts.extend(f"- {link.label}: {link.url}" for link in summary.important_links)
            else:
                parts.append("- (none provided)")

            parts.extend(["", "Use the user's edit request to adjust this preview."])
            return "\n".join(parts)

    async def revise_summary(
        self, *, repository: RepositoryInfo, summary: RepositorySummary, edit_request: str
    ) -> RepositorySummary:
        deps = _build_revision_dependencies(repository, summary)
        instructions = "Edit request from the user:\n" + edit_request.strip()

        try:
            result = await self._edit_agent.run(instructions, deps=deps)
        except Exception as exc:
            raise PreviewEditError(original_error=exc) from exc

        return result.output


def _build_dependencies(repository: RepositoryInfo) -> RepositorySummaryDependencies:
    readme = _extract_readme(repository)
    return RepositorySummaryDependencies(repository=repository, readme_excerpt=readme, links=_extract_links(readme))


def _build_revision_dependencies(
    repository: RepositoryInfo, summary: RepositorySummary
) -> RepositorySummaryRevisionDependencies:
    return RepositorySummaryRevisionDependencies(repository=repository, current_summary=summary)


def _extract_readme(repository: RepositoryInfo) -> str:
    if not repository.readme or not repository.readme.content:
        return ""

    content = repository.readme.content.strip()
    if len(content) <= _MAX_README_CHARS:
        return content

    return f"{content[:_MAX_README_CHARS].rstrip()}..."


def _extract_links(text: str) -> list[str]:
    seen: set[str] = set()
    results: list[str] = []
    if not text:
        return results

    for match in _URL_PATTERN.findall(text):
        url = match.rstrip(".,);]\"' ")
        if url and url not in seen:
            seen.add(url)
            results.append(url)

    return results
