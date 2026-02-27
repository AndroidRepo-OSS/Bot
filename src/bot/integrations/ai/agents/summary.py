# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations

from typing import TYPE_CHECKING, Final, override

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
from .context import append_bullet_block, append_text_block, render_repository_section

logger = get_logger(__name__)

if TYPE_CHECKING:
    from bot.integrations.repositories.models import RepositoryInfo

type SummaryOutput = RepositorySummary | RejectedRepository

_SUMMARY_REQUEST: Final[str] = (
    "Generate a structured summary for this repository. "
    "Validate first that it is Android-related. "
    "Return RejectedRepository when it is not Android-related or cannot be summarized confidently. "
    "Otherwise return RepositorySummary using only the provided repository data."
)


class SummaryAgent(BaseAgent[SummaryDependencies, SummaryOutput]):
    __slots__ = ()

    _deps_type = SummaryDependencies
    _instructions = SUMMARY_INSTRUCTIONS
    _model_names = ("openai/gpt-5", "openai/gpt-5-mini", "openai/gpt-4.1", "openai/gpt-4.1-mini")
    _output_type = SummaryOutput

    @override
    def build_context(self, deps: SummaryDependencies) -> str:
        parts = render_repository_section(deps.repository, include_author=True)

        if deps.reuse_tags:
            parts.extend([
                "",
                "## Reuse Tags (MANDATORY)",
                "This project was previously posted. You MUST use exactly these tags:",
            ])
            parts.extend(f"- {tag}" for tag in deps.reuse_tags)
            parts.append("Do NOT select different tags; use only the ones listed above.")
        else:
            append_bullet_block(parts, "## Allowed Tags (choose 2-4)", deps.available_tags)

        if deps.links:
            append_bullet_block(parts, "## Available Links (select relevant ones)", deps.links)

        append_text_block(
            parts,
            "## README Content",
            deps.readme_excerpt,
            intro="Use this to extract features, benefits, and additional context:",
        )

        return "\n".join(parts)

    async def summarize(
        self, repository: RepositoryInfo, *, reuse_tags: tuple[str, ...] | None = None
    ) -> SummaryResult:
        await logger.ainfo(
            "Starting repository summary generation",
            repository=repository.full_name,
            platform=repository.platform.value,
            has_readme=repository.has_readme,
            reuse_tags_count=len(reuse_tags) if reuse_tags else 0,
        )

        readme_excerpt = extract_readme(repository)
        available_links = tuple(extract_links(readme_excerpt))

        await logger.adebug(
            "Summary context prepared",
            repository=repository.full_name,
            readme_length=len(readme_excerpt),
            links_count=len(available_links),
        )

        deps = SummaryDependencies(
            repository=repository,
            readme_excerpt=readme_excerpt,
            links=available_links,
            available_tags=() if reuse_tags else ALLOWED_SUMMARY_TAGS,
            reuse_tags=reuse_tags,
        )

        try:
            await logger.adebug("Invoking AI agent for summary", repository=repository.full_name)
            result = await self._agent.run(_SUMMARY_REQUEST, deps=deps)
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
                "Repository rejected as non-Android project",
                repository=repository.full_name,
                reason=output.reason,
                model_name=model_name,
            )
            raise NonAndroidProjectError(reason=output.reason)

        await logger.ainfo(
            "Repository summary generated successfully",
            repository=repository.full_name,
            project_name=output.project_name,
            features_count=len(output.key_features),
            links_count=len(output.important_links),
            tags_count=len(output.tags),
            model_name=model_name,
        )

        return SummaryResult(summary=output, model_name=model_name)
