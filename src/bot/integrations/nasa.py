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

        media_type = metadata.get("media_type")
        if media_type == "image":
            url = metadata.get("hdurl") or metadata.get("url")
        else:
            url = metadata.get("thumbnail_url") or metadata.get("url")
        if not isinstance(url, str):
            return None

        return await self._download_image(url)

    async def _fetch_metadata(self) -> dict[str, object] | None:
        try:
            async with self.session.get(
                APOD_ENDPOINT, params={"api_key": self.api_key, "count": 1, "thumbs": "true"}
            ) as response:
                if response.status != 200:
                    return None
                payload = await response.json()
        except ClientError, ContentTypeError, OSError, ValueError:
            return None

        candidates: list[dict[str, object]] = []
        if isinstance(payload, list):
            candidates = [item for item in payload if isinstance(item, dict)]
        elif isinstance(payload, dict):
            candidates = [payload]

        for candidate in candidates:
            media_type = candidate.get("media_type")
            if media_type in {"image", "video"}:
                return candidate

        return None

    async def _download_image(self, url: str) -> bytes | None:
        try:
            async with self.session.get(url) as response:
                if response.status != 200:
                    return None
                return await response.read()
        except ClientError, OSError:
            return None
