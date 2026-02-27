# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations

from typing import TYPE_CHECKING, Final, override

from bot.integrations.ai.errors import PreviewEditError
from bot.integrations.ai.models import ALLOWED_SUMMARY_TAGS, RepositorySummary, RevisionDependencies, RevisionResult
from bot.integrations.ai.prompts import REVISION_INSTRUCTIONS
from bot.logging import get_logger

from .base import BaseAgent
from .context import append_bullet_block, render_repository_section, render_summary_section

logger = get_logger(__name__)

if TYPE_CHECKING:
    from bot.integrations.repositories.models import RepositoryInfo

_REVISION_REQUEST_PREFIX: Final[str] = "Edit request from the user:\n"


class RevisionAgent(BaseAgent[RevisionDependencies, RepositorySummary]):
    __slots__ = ()

    _deps_type = RevisionDependencies
    _instructions = REVISION_INSTRUCTIONS
    _model_names = ("openai/gpt-5-mini", "openai/gpt-4.1-mini")
    _output_type = RepositorySummary

    @override
    def build_context(self, deps: RevisionDependencies) -> str:
        parts = render_repository_section(deps.repository)
        parts.extend(["", *render_summary_section(deps.current_summary)])
        append_bullet_block(parts, "## Allowed Tags (choose 2-4)", ALLOWED_SUMMARY_TAGS)
        parts.extend(["", "Use the user's edit request to adjust this preview."])
        return "\n".join(parts)

    async def revise(
        self, *, repository: RepositoryInfo, summary: RepositorySummary, edit_request: str
    ) -> RevisionResult:
        await logger.ainfo(
            "Starting preview revision",
            repository=repository.full_name,
            current_project_name=summary.project_name,
            edit_request_length=len(edit_request),
        )

        deps = RevisionDependencies(repository=repository, current_summary=summary)
        prompt = _REVISION_REQUEST_PREFIX + edit_request.strip()

        await logger.adebug(
            "Revision context prepared",
            repository=repository.full_name,
            current_features_count=len(summary.key_features),
            current_links_count=len(summary.important_links),
        )

        try:
            await logger.adebug("Invoking AI agent for revision", repository=repository.full_name)
            result = await self._agent.run(prompt, deps=deps)
        except Exception as exc:
            await logger.aerror(
                "Failed to revise preview",
                repository=repository.full_name,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            raise PreviewEditError(original_error=exc) from exc

        model_name = result.response.model_name or "unknown"

        await logger.ainfo(
            "Preview revision completed successfully",
            repository=repository.full_name,
            new_project_name=result.output.project_name,
            new_features_count=len(result.output.key_features),
            new_links_count=len(result.output.important_links),
            new_tags_count=len(result.output.tags),
            model_name=model_name,
        )

        return RevisionResult(summary=result.output, model_name=model_name)
