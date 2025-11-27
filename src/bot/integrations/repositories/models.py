# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations

from enum import StrEnum

from pydantic import AnyHttpUrl, BaseModel, ConfigDict  # noqa: TC002


class RepositoryPlatform(StrEnum):
    GITHUB = "github"
    GITLAB = "gitlab"


class RepositoryAuthor(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    id: int | str
    username: str
    display_name: str | None = None
    url: AnyHttpUrl | None = None


class RepositoryReadme(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    path: str = "README.md"
    content: str
    source_url: AnyHttpUrl | None = None


class RepositoryInfo(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    platform: RepositoryPlatform
    id: int | str
    name: str
    full_name: str
    description: str | None = None
    web_url: AnyHttpUrl
    tags: list[str] = []
    readme: RepositoryReadme | None = None
    author: RepositoryAuthor
