# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Self

from aiohttp import ClientResponseError

from .errors import RepositoryClientError, RepositoryNotFoundError

if TYPE_CHECKING:
    from aiohttp import ClientSession

    from bot.integrations.repositories.models import RepositoryInfo


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

    async def _make_request(
        self,
        url: str,
        *,
        method: str = "GET",
        params: dict[str, str | int] | None = None,
        return_json: bool = True,
        return_bytes: bool = False,
        ignore_404: bool = False,
    ) -> object | bytes | str | None:
        if return_json and return_bytes:
            msg = "return_json and return_bytes cannot both be True"
            raise ValueError(msg)

        async with self._session.request(method, url, headers=self._headers, params=params) as response:
            if response.status == 404:
                if ignore_404:
                    return None
                raise RepositoryNotFoundError(self._platform_name)

            try:
                response.raise_for_status()
            except ClientResponseError as exc:
                body = await response.text()
                raise RepositoryClientError(self._platform_name, status=exc.status, details=body) from exc

            if return_bytes:
                return await response.read()
            if return_json:
                return await response.json()
            return await response.text()

    async def aclose(self) -> None:
        if not self._session.closed:
            await self._session.close()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_exc_info: object) -> None:
        await self.aclose()

    @abstractmethod
    async def fetch_repository(self, owner: str, name: str) -> RepositoryInfo: ...
