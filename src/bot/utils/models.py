# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class GitHubRepository(BaseModel):
    """Represents a GitHub repository with essential metadata."""

    id: int = Field(..., description="GitHub repository ID (unique identifier)")
    name: str = Field(..., description="Repository name")
    full_name: str = Field(..., description="Full repository name (owner/repo)")
    owner: str = Field(..., description="Repository owner")
    description: str | None = Field(None, description="Repository description")
    url: str = Field(..., description="Repository URL")
    topics: list[str] = Field(default_factory=list, description="Repository topics/tags")
    readme_content: str | None = Field(None, description="README content (truncated)")


class ImportantLink(BaseModel):
    """Represents an important link with its metadata."""

    title: str = Field(..., description="Human-readable title for the link")
    url: str = Field(..., description="Valid URL to the resource")
    type: Literal["download", "website", "documentation", "demo", "store", "repository"] = Field(
        ..., description="Category of the link"
    )


class AIGeneratedContent(BaseModel):
    """AI-generated content for repository posts."""

    enhanced_description: str = Field(
        ..., description="User-focused description explaining benefits and problems solved"
    )
    relevant_tags: list[str] = Field(
        default_factory=list, description="Relevant tags for categorizing the Android app or tool"
    )
    key_features: list[str] = Field(
        default_factory=list, description="Key features that users will find valuable"
    )
    important_links: list[ImportantLink] = Field(
        default_factory=list, description="Important links for downloads, docs, or websites"
    )


class EnhancedRepositoryData(BaseModel):
    """Repository data enhanced with AI-generated content."""

    repository: GitHubRepository
    ai_content: AIGeneratedContent | None = None
