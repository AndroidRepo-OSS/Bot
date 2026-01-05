# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bot.integrations.repositories import RepositoryInfo


@dataclass(slots=True)
class PreviewDebugEntry:
    repository: RepositoryInfo
    summary_model: str | None = None
    revision_model: str | None = None


class PreviewDebugRegistry:
    __slots__ = ("_entries", "_limit")

    def __init__(self, *, max_entries: int = 50) -> None:
        self._entries: OrderedDict[str, PreviewDebugEntry] = OrderedDict()
        self._limit = max_entries

    def save(self, submission_id: str, repository: RepositoryInfo, *, summary_model: str | None = None) -> None:
        if submission_id in self._entries:
            entry = self._entries[submission_id]
            entry.repository = repository
            if summary_model:
                entry.summary_model = summary_model
            self._entries.move_to_end(submission_id)
        else:
            self._entries[submission_id] = PreviewDebugEntry(repository=repository, summary_model=summary_model)
        self._trim()

    def set_revision_model(self, submission_id: str, model_name: str | None) -> None:
        if submission_id in self._entries:
            self._entries[submission_id].revision_model = model_name

    def get(self, submission_id: str) -> PreviewDebugEntry | None:
        return self._entries.get(submission_id)

    def discard(self, submission_id: str) -> None:
        self._entries.pop(submission_id, None)

    def _trim(self) -> None:
        while len(self._entries) > self._limit:
            self._entries.popitem(last=False)
