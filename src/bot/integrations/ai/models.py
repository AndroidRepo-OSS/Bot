# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field  # noqa: TC002

if TYPE_CHECKING:
    from bot.integrations.repositories.models import RepositoryInfo


@dataclass(slots=True)
class SummaryDependencies:
    repository: RepositoryInfo
    readme_excerpt: str
    links: list[str]


@dataclass(slots=True)
class RevisionDependencies:
    repository: RepositoryInfo
    current_summary: RepositorySummary


@dataclass(slots=True)
class SummaryResult:
    summary: RepositorySummary
    model_name: str


@dataclass(slots=True)
class RevisionResult:
    summary: RepositorySummary
    model_name: str


class ImportantLink(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    label: str = Field(
        min_length=1,
        max_length=120,
        description="Descriptive name (e.g., 'Download (Latest Release)', 'F-Droid', 'Google Play')",
    )
    url: AnyHttpUrl = Field(description="The full URL")


class RepositorySummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    project_name: str = Field(
        min_length=1, description="The project's display name, extracted from README or documentation"
    )
    enhanced_description: str = Field(
        min_length=1, max_length=280, description="2-3 sentences highlighting user benefits and target audience"
    )
    key_features: list[str] = Field(
        default_factory=list, max_length=4, description="3-4 concise, user-centric features"
    )
    important_links: list[ImportantLink] = Field(
        default_factory=list,
        description="Relevant external links (downloads, stores, docs). Exclude the main repository/README URL.",
    )


class RejectedRepository(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    reason: str = Field(
        min_length=1,
        max_length=200,
        description="Brief explanation of why the repository was rejected (not Android-related)",
    )
