# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, computed_field


class BaseRepository(BaseModel):
    id: int = Field(..., description="Repository ID (unique identifier)")
    name: str = Field(..., description="Repository name")
    full_name: str = Field(..., description="Full repository name (owner/repo)")
    owner: str = Field(..., description="Repository owner")
    description: str | None = Field(None, description="Repository description")
    url: str = Field(..., description="Repository URL")
    topics: list[str] = Field(default_factory=list, description="Repository topics/tags")
    readme_content: str | None = Field(None, description="README content (truncated)")

    @computed_field
    @property
    def has_description(self) -> bool:
        return bool(self.description and self.description.strip())

    @computed_field
    @property
    def has_topics(self) -> bool:
        return bool(self.topics)

    @computed_field
    @property
    def has_readme(self) -> bool:
        return bool(self.readme_content and self.readme_content.strip())


class GitHubRepository(BaseRepository): ...


class GitLabRepository(BaseRepository): ...


class ImportantLink(BaseModel):
    title: str = Field(..., description="Human-readable title for the link")
    url: str = Field(..., description="Valid URL to the resource")
    type: Literal["download", "website", "documentation", "demo", "store", "repository"] = Field(
        ..., description="Category of the link"
    )


class AIGeneratedContent(BaseModel):
    project_name: str = Field(
        ..., description="The actual project name (may differ from repository name)"
    )
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

    @computed_field
    @property
    def has_features(self) -> bool:
        return bool(self.key_features)

    @computed_field
    @property
    def has_links(self) -> bool:
        return bool(self.important_links)

    @computed_field
    @property
    def has_tags(self) -> bool:
        return bool(self.relevant_tags)


class EnhancedRepositoryData(BaseModel):
    repository: GitHubRepository | GitLabRepository
    ai_content: AIGeneratedContent | None = None

    @computed_field
    @property
    def is_github(self) -> bool:
        return isinstance(self.repository, GitHubRepository)

    @computed_field
    @property
    def is_gitlab(self) -> bool:
        return isinstance(self.repository, GitLabRepository)

    @computed_field
    @property
    def platform_name(self) -> str:
        return "GitHub" if self.is_github else "GitLab"

    @computed_field
    @property
    def has_ai_content(self) -> bool:
        return self.ai_content is not None
