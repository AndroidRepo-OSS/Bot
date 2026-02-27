# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from aiohttp import ClientResponseError, ContentTypeError

from bot.integrations.repositories.errors import RepositoryClientError, RepositoryNotFoundError
from bot.logging import get_logger

if TYPE_CHECKING:
    from collections.abc import Iterable

    from aiohttp import ClientSession

    from bot.integrations.repositories.models import RepositoryInfo

type JSONObject = dict[str, Any]
type JSONArray = list[Any]
type JSONPayload = JSONObject | JSONArray

logger = get_logger(__name__)

_README_TRUNCATION_SUFFIX = "\n\n[Content truncated...]"


class ResponseFormat(StrEnum):
    JSON = "json"
    TEXT = "text"
    BYTES = "bytes"


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
    def _format_error_details(details: str | None, *, limit: int = 300) -> str | None:
        if not details:
            return None

        cleaned = details.strip()
        if not cleaned:
            return None

        if len(cleaned) <= limit:
            return cleaned

        return f"{cleaned[:limit].rstrip()}..."

    @staticmethod
    def _string_value(value: object) -> str | None:
        if not isinstance(value, str):
            return None

        cleaned = value.strip()
        return cleaned or None

    @staticmethod
    def _mapping_value(value: object) -> JSONObject:
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _identifier_value(value: object, *, fallback: int | str = 0) -> int | str:
        if isinstance(value, int):
            return value

        if isinstance(value, str):
            cleaned = value.strip()
            if cleaned:
                return cleaned

        return fallback

    @staticmethod
    def _unique_strings(values: Iterable[object]) -> list[str]:
        seen: set[str] = set()
        unique_values: list[str] = []

        for value in values:
            cleaned = BaseRepositoryFetcher._string_value(value)
            if cleaned is None or cleaned in seen:
                continue

            seen.add(cleaned)
            unique_values.append(cleaned)

        return unique_values

    def _require_string(self, payload: JSONObject, field: str, *, source: str) -> str:
        value = self._string_value(payload.get(field))
        if value is not None:
            return value

        raise RepositoryClientError(self._platform_name, details=f"Missing {source} field: {field}")

    @staticmethod
    def _sanitize_readme_content(content: str, *, max_length: int = 50_000) -> str:
        sanitized = content.strip()
        if len(sanitized) <= max_length:
            return sanitized

        clipped = sanitized[:max_length].rstrip()
        return f"{clipped}{_README_TRUNCATION_SUFFIX}"

    @staticmethod
    def _unwrap_client_error(exc_group: BaseExceptionGroup[RepositoryClientError]) -> RepositoryClientError:
        first = exc_group.exceptions[0]
        if isinstance(first, RepositoryClientError):
            return first

        msg = "except* RepositoryClientError captured an unexpected exception type"
        raise TypeError(msg)

    async def _request(
        self,
        url: str,
        *,
        method: str = "GET",
        params: dict[str, str | int] | None = None,
        response_format: ResponseFormat = ResponseFormat.JSON,
        ignore_404: bool = False,
    ) -> JSONPayload | str | bytes | None:
        await logger.adebug(
            "Making API request",
            platform=self._platform_name,
            method=method,
            url=url,
            has_params=params is not None,
            response_format=response_format.value,
        )

        async with self._session.request(method, url, headers=self._headers, params=params) as response:
            if response.status == 404:
                if ignore_404:
                    await logger.adebug("Resource not found (ignored)", platform=self._platform_name, url=url)
                    return None

                await logger.awarning("Repository not found", platform=self._platform_name, url=url)
                raise RepositoryNotFoundError(self._platform_name)

            try:
                response.raise_for_status()
            except ClientResponseError as exc:
                body = await response.text()
                details = self._format_error_details(body)
                await logger.aerror(
                    "API request failed", platform=self._platform_name, url=url, status=exc.status, details=details
                )
                raise RepositoryClientError(self._platform_name, status=exc.status, details=details) from exc

            await logger.adebug(
                "API request successful",
                platform=self._platform_name,
                url=url,
                status=response.status,
                response_format=response_format.value,
            )

            if response_format is ResponseFormat.BYTES:
                return await response.read()

            if response_format is ResponseFormat.TEXT:
                return await response.text()

            try:
                payload = await response.json()
            except (ContentTypeError, ValueError) as exc:
                body = await response.text()
                details = self._format_error_details(body) or "Unexpected non-JSON response"
                await logger.aerror(
                    "Failed to decode JSON response",
                    platform=self._platform_name,
                    url=url,
                    status=response.status,
                    details=details,
                )
                raise RepositoryClientError(self._platform_name, status=response.status, details=details) from exc

            if isinstance(payload, dict | list):
                return payload

            msg = f"Unexpected JSON payload type: {type(payload).__name__}"
            raise RepositoryClientError(self._platform_name, status=response.status, details=msg)

    async def _request_object(
        self,
        url: str,
        *,
        method: str = "GET",
        params: dict[str, str | int] | None = None,
        ignore_404: bool = False,
        details: str,
    ) -> JSONObject | None:
        payload = await self._request(
            url, method=method, params=params, response_format=ResponseFormat.JSON, ignore_404=ignore_404
        )

        if payload is None:
            return None

        if isinstance(payload, dict):
            return payload

        raise RepositoryClientError(self._platform_name, details=details)

    async def _request_array(
        self,
        url: str,
        *,
        method: str = "GET",
        params: dict[str, str | int] | None = None,
        ignore_404: bool = False,
        details: str,
    ) -> JSONArray | None:
        payload = await self._request(
            url, method=method, params=params, response_format=ResponseFormat.JSON, ignore_404=ignore_404
        )

        if payload is None:
            return None

        if isinstance(payload, list):
            return payload

        raise RepositoryClientError(self._platform_name, details=details)

    async def _request_text(
        self, url: str, *, method: str = "GET", params: dict[str, str | int] | None = None, ignore_404: bool = False
    ) -> str | None:
        payload = await self._request(
            url, method=method, params=params, response_format=ResponseFormat.TEXT, ignore_404=ignore_404
        )

        if payload is None:
            return None

        if isinstance(payload, str):
            return payload

        msg = f"Unexpected text payload type: {type(payload).__name__}"
        raise RepositoryClientError(self._platform_name, details=msg)

    @abstractmethod
    async def fetch_repository(self, owner: str, name: str) -> RepositoryInfo: ...
