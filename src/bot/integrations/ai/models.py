# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations

from pydantic import AnyHttpUrl, BaseModel, ConfigDict  # noqa: TC002

from bot.integrations.repositories.models import RepositoryInfo  # noqa: TC001


class RepositorySummaryDependencies(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    repository: RepositoryInfo
    readme_excerpt: str
    links: list[str]


class ImportantLink(BaseModel):
    """A relevant external link for the project."""

    model_config = ConfigDict(extra="forbid", frozen=True, use_attribute_docstrings=True)

    label: str
    """Descriptive name (e.g., 'Download (Latest Release)', 'F-Droid', 'Google Play', 'Telegram Channel')"""

    url: AnyHttpUrl
    """The full URL"""


class RepositorySummary(BaseModel):
    """Marketing summary of an Android repository for the AndroidRepo Telegram channel."""

    model_config = ConfigDict(extra="forbid", frozen=True, use_attribute_docstrings=True)

    project_name: str
    """The project's display name, extracted from README or documentation"""

    enhanced_description: str
    """2-3 sentences highlighting user benefits and target audience (max 280 chars)"""

    key_features: list[str] = []
    """3-4 concise, user-centric features"""

    important_links: list[ImportantLink] = []
    """Relevant external links (downloads, stores, docs). Exclude the main repository/README URL."""


class RepositorySummaryRevisionDependencies(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    repository: RepositoryInfo
    current_summary: RepositorySummary
