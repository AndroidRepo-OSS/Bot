# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations


class RepositoryClientError(RuntimeError):
    __slots__ = ("details", "platform", "status")

    def __init__(self, platform: str, *, status: int | None = None, details: str | None = None) -> None:
        message = f"{platform} API request failed"
        if status is not None:
            message = f"{message} (status {status})"
        if details:
            message = f"{message}: {details}"

        super().__init__(message)

        self.platform = platform
        self.status = status
        self.details = details


class RepositoryNotFoundError(RepositoryClientError):
    def __init__(self, platform: str) -> None:
        super().__init__(platform, details="Repository not found")
