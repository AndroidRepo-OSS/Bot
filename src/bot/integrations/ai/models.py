# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from pydantic import AnyHttpUrl, BaseModel, ConfigDict  # noqa: TC002

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


class ImportantLink(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, use_attribute_docstrings=True)

    label: str
    """Descriptive name (e.g., 'Download (Latest Release)', 'F-Droid', 'Google Play', 'Telegram Channel')"""

    url: AnyHttpUrl
    """The full URL"""


class RepositorySummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, use_attribute_docstrings=True)

    project_name: str
    """The project's display name, extracted from README or documentation"""

    enhanced_description: str
    """2-3 sentences highlighting user benefits and target audience (max 280 chars)"""

    key_features: list[str] = []
    """3-4 concise, user-centric features"""

    important_links: list[ImportantLink] = []
    """Relevant external links (downloads, stores, docs). Exclude the main repository/README URL."""
