# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations

from pydantic import BaseModel, Field


class GitHubRepository(BaseModel):
    name: str = Field(..., description="Repository name")
    full_name: str = Field(..., description="Full repository name (owner/repo)")
    owner: str = Field(..., description="Repository owner")
    description: str | None = Field(None, description="Repository description")
    url: str = Field(..., description="Repository URL")
    topics: list[str] = Field(default_factory=list, description="Repository topics/tags")
    readme_content: str | None = Field(None, description="README content (truncated)")


class AIGeneratedContent(BaseModel):
    """AI-generated content for repository posts."""

    enhanced_description: str = Field(..., description="AI-enhanced repository description")
    relevant_tags: list[str] = Field(
        default_factory=list, description="AI-suggested relevant tags"
    )
    key_features: list[str] = Field(
        default_factory=list, description="Key features extracted from README"
    )
    important_links: list[dict[str, str]] = Field(
        default_factory=list, description="Important links found in README"
    )


class EnhancedRepositoryData(BaseModel):
    """Repository data enhanced with AI-generated content."""

    repository: GitHubRepository
    ai_content: AIGeneratedContent | None = None
