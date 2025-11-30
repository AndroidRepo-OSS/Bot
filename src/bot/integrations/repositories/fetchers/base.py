# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Self

from aiohttp import ClientResponseError

from bot.integrations.repositories.errors import RepositoryClientError, RepositoryNotFoundError
from bot.logging import get_logger

if TYPE_CHECKING:
    from aiohttp import ClientSession

    from bot.integrations.repositories.models import RepositoryInfo

logger = get_logger(__name__)


class BaseRepositoryFetcher(ABC):
    __slots__ = ("_session",)

    def __init__(self, *, session: ClientSession) -> None:
        self._session = session

    @property
    @abstractmethod
    def _headers(self) -> dict[str, str]: ...

    @property
    @abstractmethod
    def _platform_name(self) -> str: ...

    @staticmethod
    def _sanitize_readme_content(content: str, *, max_length: int = 50000) -> str:
        sanitized = content.strip()
        if len(sanitized) > max_length:
            return sanitized[:max_length] + "\n\n[Content truncated...]"
        return sanitized

    async def _make_request[T: (dict, list, bytes, str, None)](
        self,
        url: str,
        *,
        method: str = "GET",
        params: dict[str, str | int] | None = None,
        return_json: bool = True,
        return_bytes: bool = False,
        ignore_404: bool = False,
    ) -> T:
        if return_json and return_bytes:
            msg = "return_json and return_bytes cannot both be True"
            raise ValueError(msg)

        await logger.adebug(
            "Making API request", platform=self._platform_name, method=method, url=url, has_params=params is not None
        )

        async with self._session.request(method, url, headers=self._headers, params=params) as response:
            if response.status == 404:
                if ignore_404:
                    await logger.adebug("Resource not found (ignored)", platform=self._platform_name, url=url)
                    return None  # type: ignore[return-value]
                await logger.awarning("Repository not found", platform=self._platform_name, url=url)
                raise RepositoryNotFoundError(self._platform_name)

            try:
                response.raise_for_status()
            except ClientResponseError as exc:
                body = await response.text()
                await logger.aerror(
                    "API request failed",
                    platform=self._platform_name,
                    url=url,
                    status=exc.status,
                    details=body[:200] if body else None,
                )
                raise RepositoryClientError(self._platform_name, status=exc.status, details=body) from exc

            await logger.adebug("API request successful", platform=self._platform_name, url=url, status=response.status)

            if return_bytes:
                return await response.read()  # type: ignore[return-value]
            if return_json:
                return await response.json()  # type: ignore[return-value]
            return await response.text()  # type: ignore[return-value]

    async def aclose(self) -> None:
        if not self._session.closed:
            await self._session.close()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_exc_info: object) -> None:
        await self.aclose()

    @abstractmethod
    async def fetch_repository(self, owner: str, name: str) -> RepositoryInfo: ...
