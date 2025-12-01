# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations

from typing import TYPE_CHECKING

from bot.integrations.ai.errors import PreviewEditError
from bot.integrations.ai.models import RepositorySummary, RevisionDependencies
from bot.integrations.ai.prompts import REVISION_INSTRUCTIONS
from bot.logging import get_logger

from .base import BaseAgent

logger = get_logger(__name__)

if TYPE_CHECKING:
    from pydantic_ai import RunContext

    from bot.integrations.repositories.models import RepositoryInfo


class RevisionAgent(BaseAgent[RevisionDependencies, RepositorySummary]):
    __slots__ = ()

    def __init__(self, *, api_key: str) -> None:
        super().__init__(api_key=api_key, instructions=REVISION_INSTRUCTIONS)

    @classmethod
    def _get_output_type(cls) -> type[RepositorySummary]:
        return RepositorySummary

    @classmethod
    def _get_deps_type(cls) -> type[RevisionDependencies]:
        return RevisionDependencies

    def _register_instructions(self) -> None:
        @self._agent.instructions
        def provide_revision_context(ctx: RunContext[RevisionDependencies]) -> str:
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

    async def revise(
        self, *, repository: RepositoryInfo, summary: RepositorySummary, edit_request: str
    ) -> RepositorySummary:
        await logger.ainfo(
            "Starting preview revision",
            repository=repository.full_name,
            current_project_name=summary.project_name,
            edit_request_length=len(edit_request),
        )

        deps = RevisionDependencies(repository=repository, current_summary=summary)
        instructions = "Edit request from the user:\n" + edit_request.strip()

        await logger.adebug(
            "Revision context prepared",
            repository=repository.full_name,
            current_features_count=len(summary.key_features),
            current_links_count=len(summary.important_links),
        )

        try:
            await logger.adebug("Invoking AI agent for revision", repository=repository.full_name)
            result = await self._agent.run(instructions, deps=deps)
        except Exception as exc:
            await logger.aerror(
                "Failed to revise preview",
                repository=repository.full_name,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            raise PreviewEditError(original_error=exc) from exc

        await logger.ainfo(
            "Preview revision completed successfully",
            repository=repository.full_name,
            new_project_name=result.output.project_name,
            new_features_count=len(result.output.key_features),
            new_links_count=len(result.output.important_links),
        )

        return result.output
