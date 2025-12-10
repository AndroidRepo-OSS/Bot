# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from pydantic import AnyHttpUrl


class RepositoryPlatform(StrEnum):
    GITHUB = "github"
    GITLAB = "gitlab"


class RepositoryAuthor(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    id: int | str = Field(description="Unique author identifier (numeric for GitHub, string for GitLab)")
    username: str = Field(min_length=1, description="Author's username/login")
    display_name: str | None = Field(default=None, description="Author's display name")
    url: AnyHttpUrl | None = Field(default=None, description="Author's profile URL")


class RepositoryReadme(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    path: str = Field(default="README.md", min_length=1, description="Path to README file")
    content: str = Field(min_length=1, description="README content")
    source_url: AnyHttpUrl | None = Field(default=None, description="URL to raw README content")


class RepositoryInfo(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    platform: RepositoryPlatform = Field(description="Repository hosting platform")
    id: int | str = Field(description="Unique repository identifier")
    name: str = Field(min_length=1, description="Repository name")
    full_name: str = Field(min_length=1, description="Full repository path (owner/name)")
    description: str | None = Field(default=None, description="Repository description")
    web_url: AnyHttpUrl = Field(description="Repository web URL")
    tags: list[str] = Field(default_factory=list, description="Repository topics/tags")
    readme: RepositoryReadme | None = Field(default=None, description="Repository README content")
    author: RepositoryAuthor = Field(description="Repository author/owner")
