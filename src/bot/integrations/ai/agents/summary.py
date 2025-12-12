# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations

from typing import TYPE_CHECKING

from bot.integrations.ai.errors import NonAndroidProjectError, RepositorySummaryError
from bot.integrations.ai.models import (
    ALLOWED_SUMMARY_TAGS,
    RejectedRepository,
    RepositorySummary,
    SummaryDependencies,
    SummaryResult,
)
from bot.integrations.ai.prompts import SUMMARY_INSTRUCTIONS
from bot.integrations.ai.utils import extract_links, extract_readme
from bot.logging import get_logger

from .base import BaseAgent

logger = get_logger(__name__)

if TYPE_CHECKING:
    from pydantic_ai import RunContext

    from bot.integrations.repositories.models import RepositoryInfo

type SummaryOutput = RepositorySummary | RejectedRepository


class SummaryAgent(BaseAgent[SummaryDependencies, SummaryOutput]):
    __slots__ = ()

    def __init__(self, *, api_key: str) -> None:
        super().__init__(api_key=api_key, instructions=SUMMARY_INSTRUCTIONS)

    @classmethod
    def _get_output_type(cls) -> type[SummaryOutput]:
        return SummaryOutput

    @classmethod
    def _get_deps_type(cls) -> type[SummaryDependencies]:
        return SummaryDependencies

    def _register_instructions(self) -> None:
        @self._agent.instructions
        def provide_repository_context(ctx: RunContext[SummaryDependencies]) -> str:
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

            if ctx.deps.reuse_tags:
                parts.extend([
                    "",
                    "## Reuse Tags (MANDATORY)",
                    "This project was previously posted. You MUST use exactly these tags:",
                ])
                parts.extend(f"- {tag}" for tag in ctx.deps.reuse_tags)
                parts.append("Do NOT select different tags; use only the ones listed above.")
            else:
                parts.extend(["", "## Allowed Tags (choose 2-4)"])
                parts.extend(f"- {tag}" for tag in ctx.deps.available_tags)

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

    async def summarize(
        self, repository: RepositoryInfo, *, reuse_tags: tuple[str, ...] | None = None
    ) -> SummaryResult:
        await logger.ainfo(
            "Starting repository summary generation",
            repository=repository.full_name,
            platform=repository.platform.value,
            has_readme=bool(repository.readme and repository.readme.content),
            reuse_tags_count=len(reuse_tags) if reuse_tags else 0,
        )

        readme = extract_readme(repository)
        links = extract_links(readme)

        await logger.adebug(
            "Extracted README and links for summary",
            repository=repository.full_name,
            readme_length=len(readme),
            links_count=len(links),
        )

        deps = SummaryDependencies(
            repository=repository,
            readme_excerpt=readme,
            links=links,
            available_tags=ALLOWED_SUMMARY_TAGS if not reuse_tags else (),
            reuse_tags=reuse_tags,
        )

        try:
            await logger.adebug("Invoking AI agent for summary", repository=repository.full_name)
            result = await self._agent.run(
                "Generate a summary for this Android project. "
                "First, verify if this is an Android-related project. "
                "If not, return a RejectedRepository with the reason. "
                "Otherwise, extract the project name, write a compelling description, "
                "identify key features, select relevant links, and choose 2-4 tags "
                "from the allowed list that best fit the project.",
                deps=deps,
            )
        except Exception as exc:
            await logger.aerror(
                "Failed to generate repository summary",
                repository=repository.full_name,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            raise RepositorySummaryError(original_error=exc) from exc

        output = result.output
        model_name = result.response.model_name or "unknown"

        if isinstance(output, RejectedRepository):
            await logger.ainfo(
                "Repository rejected as non-Android project", repository=repository.full_name, reason=output.reason
            )
            raise NonAndroidProjectError(reason=output.reason)

        await logger.ainfo(
            "Repository summary generated successfully",
            repository=repository.full_name,
            project_name=output.project_name,
            features_count=len(output.key_features),
            links_count=len(output.important_links),
            tags_count=len(output.tags),
        )

        return SummaryResult(summary=output, model_name=model_name)
