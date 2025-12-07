# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from aiohttp import ClientError, ContentTypeError

if TYPE_CHECKING:
    from aiohttp import ClientSession

APOD_ENDPOINT: Final[str] = "https://api.nasa.gov/planetary/apod"


class NasaApodService:
    __slots__ = ("api_key", "session")

    def __init__(self, *, session: ClientSession, api_key: str) -> None:
        self.session = session
        self.api_key = api_key

    async def fetch_image(self) -> bytes | None:
        metadata = await self._fetch_metadata()
        if not metadata:
            return None

        url = metadata.get("hdurl") or metadata.get("url")
        if not isinstance(url, str):
            return None

        return await self._download_image(url)

    async def _fetch_metadata(self) -> dict[str, object] | None:
        try:
            async with self.session.get(APOD_ENDPOINT, params={"api_key": self.api_key}) as response:
                if response.status != 200:
                    return None
                payload = await response.json()
        except ClientError, ContentTypeError, OSError, ValueError:
            return None

        if not isinstance(payload, dict):
            return None

        if payload.get("media_type") != "image":
            return None

        return payload

    async def _download_image(self, url: str) -> bytes | None:
        try:
            async with self.session.get(url) as response:
                if response.status != 200:
                    return None
                return await response.read()
        except ClientError, OSError:
            return None
