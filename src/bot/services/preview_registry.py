# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations

from collections import OrderedDict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bot.integrations.repositories import RepositoryInfo


class PreviewDebugRegistry:
    __slots__ = ("_entries", "_limit")

    def __init__(self, *, max_entries: int = 50) -> None:
        self._entries: OrderedDict[str, RepositoryInfo] = OrderedDict()
        self._limit = max_entries

    def save(self, submission_id: str, repository: RepositoryInfo) -> None:
        if submission_id in self._entries:
            self._entries.move_to_end(submission_id)
        self._entries[submission_id] = repository
        self._trim()

    def get(self, submission_id: str) -> RepositoryInfo | None:
        return self._entries.get(submission_id)

    def discard(self, submission_id: str) -> None:
        self._entries.pop(submission_id, None)

    def _trim(self) -> None:
        while len(self._entries) > self._limit:
            self._entries.popitem(last=False)
