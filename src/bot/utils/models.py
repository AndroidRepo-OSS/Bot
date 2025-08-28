# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator


class BaseRepository(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, validate_default=True, extra="forbid")

    id: int = Field(..., gt=0, description="Repository ID (unique identifier)")
    name: str = Field(..., min_length=1, description="Repository name")
    full_name: str = Field(..., min_length=1, description="Full repository name (owner/repo)")
    owner: str = Field(..., min_length=1, description="Repository owner")
    description: str | None = Field(None, description="Repository description")
    url: str = Field(..., description="Repository URL")
    topics: list[str] = Field(default_factory=list, description="Repository topics")
    readme_content: str | None = Field(None, description="README content (truncated)")

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        if not v.startswith(("http://", "https://")):
            msg = "URL must start with http:// or https://"
            raise ValueError(msg)
        return v

    @field_validator("full_name")
    @classmethod
    def validate_full_name(cls, v: str) -> str:
        if "/" not in v:
            msg = "Full name must contain owner/repo format"
            raise ValueError(msg)
        return v

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


class GitHubRepository(BaseRepository):
    model_config = ConfigDict(str_strip_whitespace=True, validate_default=True, extra="forbid")


class GitLabRepository(BaseRepository):
    model_config = ConfigDict(str_strip_whitespace=True, validate_default=True, extra="forbid")


class ImportantLink(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, validate_default=True, extra="forbid")

    title: str = Field(..., min_length=1, description="Human-readable title for the link")
    url: str = Field(..., description="Valid URL to the resource")
    type: Literal["download", "website", "documentation", "demo", "store", "repository"] = Field(
        ..., description="Category of the link"
    )

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        if not v.startswith(("http://", "https://")):
            msg = "URL must start with http:// or https://"
            raise ValueError(msg)
        return v


class AIGeneratedContent(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, validate_default=True, extra="forbid")

    project_name: str = Field(
        ..., min_length=1, description="The actual project name (may differ from repository name)"
    )
    enhanced_description: str = Field(
        ...,
        min_length=10,
        description="User-focused description explaining benefits and problems solved",
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


class EnhancedRepositoryData(BaseModel):
    model_config = ConfigDict(validate_default=True, extra="forbid")

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
