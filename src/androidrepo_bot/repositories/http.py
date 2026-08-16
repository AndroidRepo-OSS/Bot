from __future__ import annotations

from asyncio import sleep as async_sleep
from asyncio import to_thread
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from http import HTTPStatus
from time import perf_counter
from types import MappingProxyType
from typing import TYPE_CHECKING, Protocol
from urllib.parse import urlsplit

import aiohttp
import structlog

from androidrepo_bot.errors import (
    ExternalServiceError,
    ExternalServiceTimeoutError,
    RateLimitError,
    RepositoryNotFoundError,
)
from androidrepo_bot.http import ResponseTooLargeError, read_bounded_response

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Callable, Mapping

    type PayloadParser[ParsedT] = Callable[[bytes], ParsedT]

logger = structlog.get_logger(__name__)
_MAX_RESPONSE_BYTES = 4 * 1024 * 1024
_READ_BUFFER_BYTES = 64 * 1024
_MAX_RESPONSE_HEADERS = 128
_MAX_HEADER_LINE_BYTES = 8 * 1024
_SSL_TRANSPORT_CLOSE_DELAY_SECONDS = 0.25
_MAX_RETRIES = 2
_RETRY_BACKOFF_SECONDS = 0.25
_MAX_RETRY_DELAY_SECONDS = 5.0
_RETRYABLE_STATUS_CODES = frozenset({
    HTTPStatus.REQUEST_TIMEOUT,
    HTTPStatus.INTERNAL_SERVER_ERROR,
    HTTPStatus.BAD_GATEWAY,
    HTTPStatus.SERVICE_UNAVAILABLE,
    HTTPStatus.GATEWAY_TIMEOUT,
})


@dataclass(frozen=True, slots=True)
class ProviderResponse:
    status_code: int
    headers: Mapping[str, str]
    content: bytes

    @classmethod
    async def from_client_response(cls, response: aiohttp.ClientResponse, *, max_bytes: int) -> ProviderResponse:
        headers = MappingProxyType({key.casefold(): value for key, value in response.headers.items()})
        content = await read_bounded_response(response, max_bytes=max_bytes, subject="provider response")
        return cls(response.status, headers, content)

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", errors="replace")


class ProviderTransport(Protocol):
    async def get(
        self, url: str, *, headers: Mapping[str, str] | None = None, params: Mapping[str, str] | None = None
    ) -> ProviderResponse: ...

    async def get_optional(
        self, url: str, *, headers: Mapping[str, str] | None = None, params: Mapping[str, str] | None = None
    ) -> ProviderResponse | None: ...

    async def parse[ParsedT](self, response: ProviderResponse, parser: PayloadParser[ParsedT]) -> ParsedT: ...


@asynccontextmanager
async def create_http_session() -> AsyncGenerator[aiohttp.ClientSession]:
    connector = aiohttp.TCPConnector(limit=20, limit_per_host=10, keepalive_timeout=30.0)
    client_timeout = aiohttp.ClientTimeout(total=30.0, connect=10.0, sock_connect=10.0, sock_read=30.0)
    session = aiohttp.ClientSession(
        connector=connector,
        timeout=client_timeout,
        raise_for_status=False,
        cookie_jar=aiohttp.DummyCookieJar(),
        headers={"User-Agent": "androidrepo-bot/0.1"},
        auto_decompress=True,
        trust_env=False,
        read_bufsize=_READ_BUFFER_BYTES,
        max_line_size=_MAX_HEADER_LINE_BYTES,
        max_field_size=_MAX_HEADER_LINE_BYTES,
        max_headers=_MAX_RESPONSE_HEADERS,
    )
    try:
        yield session
    finally:
        await session.close()
        await async_sleep(_SSL_TRANSPORT_CLOSE_DELAY_SECONDS)


class ProviderHttpClient:
    def __init__(self, *, client: aiohttp.ClientSession, provider_name: str) -> None:
        self._client = client
        self._provider_name = provider_name

    async def get(
        self, url: str, *, headers: Mapping[str, str] | None = None, params: Mapping[str, str] | None = None
    ) -> ProviderResponse:
        response = await self.get_optional(url, headers=headers, params=params)
        if response is None:
            msg = "Repository not found"
            raise RepositoryNotFoundError(msg)
        return response

    async def get_optional(
        self, url: str, *, headers: Mapping[str, str] | None = None, params: Mapping[str, str] | None = None
    ) -> ProviderResponse | None:
        response = await self._send_get(url, headers=headers, params=params)
        if response.status_code == HTTPStatus.NOT_FOUND:
            logger.debug(
                "Provider optional resource not found",
                **self._request_log_context(url, status_code=response.status_code),
            )
            return None
        return self._validate_response(response)

    async def parse[ParsedT](self, response: ProviderResponse, parser: PayloadParser[ParsedT]) -> ParsedT:
        try:
            return await to_thread(parser, response.content)
        except (TypeError, ValueError) as error:
            logger.warning(
                "Provider response parsing failed",
                provider=self._provider_name,
                status_code=response.status_code,
                response_bytes=len(response.content),
                error_type=type(error).__name__,
            )
            msg = f"{self._provider_name} returned invalid data"
            raise ExternalServiceError(msg) from error

    async def _send_get(
        self, url: str, *, headers: Mapping[str, str] | None, params: Mapping[str, str] | None
    ) -> ProviderResponse:
        started_at = perf_counter()
        context = self._request_log_context(url, param_keys=tuple(sorted((params or {}).keys())))
        for attempt in range(_MAX_RETRIES + 1):
            try:
                async with self._client.get(url, headers=headers, params=params, allow_redirects=False) as response:
                    provider_response = await ProviderResponse.from_client_response(
                        response, max_bytes=_MAX_RESPONSE_BYTES
                    )
            except ResponseTooLargeError as error:
                logger.warning(
                    "Provider response exceeded size limit", **context, max_response_bytes=_MAX_RESPONSE_BYTES
                )
                msg = f"{self._provider_name} returned too much data"
                raise ExternalServiceError(msg) from error
            except TimeoutError as error:
                if await _retry_transport_failure(attempt, context, error, is_timeout=True):
                    continue
                msg = f"{self._provider_name} timed out"
                raise ExternalServiceTimeoutError(msg) from error
            except aiohttp.ClientError as error:
                if _is_retryable_client_error(error) and await _retry_transport_failure(
                    attempt, context, error, is_timeout=False
                ):
                    continue
                msg = f"{self._provider_name} request failed"
                raise ExternalServiceError(msg) from error

            if provider_response.status_code in _RETRYABLE_STATUS_CODES and attempt < _MAX_RETRIES:
                delay = _retry_delay(attempt, retry_after=provider_response.headers.get("retry-after"))
                logger.warning(
                    "Provider returned retryable HTTP status",
                    **context,
                    attempt=attempt + 1,
                    next_attempt=attempt + 2,
                    status_code=provider_response.status_code,
                    retry_delay_seconds=delay,
                )
                await async_sleep(delay)
                continue

            logger.debug(
                "Provider request completed",
                **context,
                attempt=attempt + 1,
                status_code=provider_response.status_code,
                duration_seconds=perf_counter() - started_at,
                response_bytes=len(provider_response.content),
            )
            return provider_response

        msg = f"{self._provider_name} request failed"
        raise ExternalServiceError(msg)

    def _validate_response(self, response: ProviderResponse) -> ProviderResponse:
        if response.status_code == HTTPStatus.TOO_MANY_REQUESTS or (
            response.status_code == HTTPStatus.FORBIDDEN and response.headers.get("x-ratelimit-remaining") == "0"
        ):
            logger.warning(
                "Provider rate limit exceeded", provider=self._provider_name, status_code=response.status_code
            )
            msg = f"{self._provider_name} rate limit exceeded"
            raise RateLimitError(msg)
        if not HTTPStatus.OK <= response.status_code < HTTPStatus.MULTIPLE_CHOICES:
            logger.warning(
                "Provider returned unsuccessful HTTP status",
                provider=self._provider_name,
                status_code=response.status_code,
            )
            msg = f"{self._provider_name} returned HTTP {response.status_code}"
            raise ExternalServiceError(msg)
        return response

    def _request_log_context(
        self, url: str, *, status_code: int | None = None, param_keys: tuple[str, ...] = ()
    ) -> dict[str, object]:
        parsed = urlsplit(url)
        context: dict[str, object] = {
            "provider": self._provider_name,
            "url_host": parsed.netloc,
            "url_path": parsed.path,
        }
        if status_code is not None:
            context["status_code"] = status_code
        if param_keys:
            context["param_keys"] = param_keys
        return context


def _is_retryable_client_error(error: aiohttp.ClientError) -> bool:
    return isinstance(error, (aiohttp.ClientConnectionError, aiohttp.ClientPayloadError)) and not isinstance(
        error, aiohttp.ClientSSLError
    )


async def _retry_transport_failure(
    attempt: int, context: dict[str, object], error: Exception, *, is_timeout: bool
) -> bool:
    if attempt >= _MAX_RETRIES:
        logger.warning(
            "Provider request timed out" if is_timeout else "Provider request failed",
            **context,
            attempt=attempt + 1,
            error_type=type(error).__name__,
            exc_info=not is_timeout,
        )
        return False
    delay = _retry_delay(attempt)
    logger.warning(
        "Provider request timed out; retrying" if is_timeout else "Provider request failed; retrying",
        **context,
        attempt=attempt + 1,
        next_attempt=attempt + 2,
        retry_delay_seconds=delay,
        error_type=type(error).__name__,
    )
    await async_sleep(delay)
    return True


def _retry_after_delay(value: str | None) -> float | None:
    if not value:
        return None
    value = value.strip()
    if value.isdecimal():
        return float(value)
    try:
        retry_at = parsedate_to_datetime(value)
    except TypeError, ValueError, IndexError, OverflowError:
        return None
    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=UTC)
    return max(0.0, (retry_at - datetime.now(UTC)).total_seconds())


def _retry_delay(attempt: int, *, retry_after: str | None = None) -> float:
    if (server_delay := _retry_after_delay(retry_after)) is not None:
        return min(server_delay, _MAX_RETRY_DELAY_SECONDS)
    return min(_RETRY_BACKOFF_SECONDS * 2**attempt, _MAX_RETRY_DELAY_SECONDS)
