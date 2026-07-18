from asyncio import sleep as async_sleep
from asyncio import to_thread
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from http import HTTPStatus
from time import perf_counter
from types import MappingProxyType
from typing import TYPE_CHECKING, Annotated, Never, TypeIs
from urllib.parse import urlsplit

import aiohttp
import structlog
from pydantic import AfterValidator, BaseModel, ConfigDict, TypeAdapter, ValidationError

from androidrepo_bot.errors import (
    ExternalServiceError,
    ExternalServiceTimeoutError,
    RateLimitError,
    RepositoryAccessError,
    RepositoryNotFoundError,
)
from androidrepo_bot.repositories.models import require_web_url

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator, Mapping

    type ResponseParser[ParsedT] = Callable[[bytes], ParsedT]

logger = structlog.get_logger(__name__)
_MAX_RESPONSE_BYTES = 4 * 1024 * 1024
_MAX_RETRIES = 2
_RETRY_BACKOFF_SECONDS = 0.25
_MAX_RETRY_DELAY_SECONDS = 5.0
_READ_CHUNK_SIZE = 64 * 1024
_LANGUAGE_USAGE_ADAPTER = TypeAdapter(dict[str, int | float], config=ConfigDict(strict=True, allow_inf_nan=False))
_RETRYABLE_STATUS_CODES = frozenset({
    HTTPStatus.REQUEST_TIMEOUT,
    HTTPStatus.BAD_GATEWAY,
    HTTPStatus.SERVICE_UNAVAILABLE,
    HTTPStatus.GATEWAY_TIMEOUT,
})
type WebUrl = Annotated[str, AfterValidator(require_web_url)]


class ProviderModel(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, strict=True, allow_inf_nan=False)


class _ResponseTooLargeError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ApiResponse:
    status_code: int
    headers: Mapping[str, str]
    content: bytes

    @classmethod
    async def from_client_response(cls, response: aiohttp.ClientResponse, *, max_bytes: int) -> ApiResponse:
        headers = MappingProxyType({key.casefold(): value for key, value in response.headers.items()})
        _validate_content_length(headers.get("content-length"), max_bytes=max_bytes)
        body = bytearray()
        async for chunk in response.content.iter_chunked(_READ_CHUNK_SIZE):
            body.extend(chunk)
            if len(body) > max_bytes:
                msg = f"provider response exceeds {max_bytes} bytes"
                raise _ResponseTooLargeError(msg)
        return cls(response.status, headers, bytes(body))

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", errors="replace")


def create_http_session() -> aiohttp.ClientSession:
    connector = aiohttp.TCPConnector(limit=20, limit_per_host=10, keepalive_timeout=30.0)
    client_timeout = aiohttp.ClientTimeout(total=30.0, connect=10.0, sock_connect=10.0, sock_read=30.0)
    return aiohttp.ClientSession(
        connector=connector,
        timeout=client_timeout,
        raise_for_status=False,
        cookie_jar=aiohttp.DummyCookieJar(),
        headers={"User-Agent": "androidrepo-bot/0.1"},
    )


class ApiClient:
    def __init__(self, *, client: aiohttp.ClientSession, provider_name: str) -> None:
        self._client = client
        self._provider_name = provider_name

    async def get(
        self, url: str, *, headers: Mapping[str, str] | None = None, params: Mapping[str, str] | None = None
    ) -> ApiResponse:
        response = await self.get_optional(url, headers=headers, params=params)
        if response is None:
            msg = "Repository not found"
            raise RepositoryNotFoundError(msg)
        return response

    async def get_optional(
        self, url: str, *, headers: Mapping[str, str] | None = None, params: Mapping[str, str] | None = None
    ) -> ApiResponse | None:
        response = await self._send_get(url, headers=headers, params=params)
        if response.status_code == HTTPStatus.NOT_FOUND:
            logger.debug(
                "Provider optional resource not found",
                **self._request_log_context(url, status_code=response.status_code),
            )
            return None
        return self._validate_response(response)

    async def parse_model[ModelT: BaseModel](self, model_type: type[ModelT], response: ApiResponse) -> ModelT:
        return await self.parse_payload(response, model_type.model_validate_json)

    async def parse_payload[ParsedT](self, response: ApiResponse, parser: ResponseParser[ParsedT]) -> ParsedT:
        try:
            return await to_thread(parser, response.content)
        except (TypeError, ValueError, ValidationError) as error:
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
    ) -> ApiResponse:
        started_at = perf_counter()
        context = self._request_log_context(url, param_keys=tuple(sorted((params or {}).keys())))
        for attempt in range(_MAX_RETRIES + 1):
            try:
                async with self._client.get(url, headers=headers, params=params) as response:
                    api_response = await ApiResponse.from_client_response(response, max_bytes=_MAX_RESPONSE_BYTES)
            except _ResponseTooLargeError as error:
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
                if await _retry_transport_failure(attempt, context, error, is_timeout=False):
                    continue
                msg = f"{self._provider_name} request failed"
                raise ExternalServiceError(msg) from error

            if api_response.status_code in _RETRYABLE_STATUS_CODES and _can_retry(attempt):
                delay = _retry_delay(attempt, retry_after=api_response.headers.get("retry-after"))
                logger.warning(
                    "Provider returned retryable HTTP status",
                    **context,
                    attempt=attempt + 1,
                    next_attempt=attempt + 2,
                    status_code=api_response.status_code,
                    retry_delay_seconds=delay,
                )
                await async_sleep(delay)
                continue

            logger.debug(
                "Provider request completed",
                **context,
                attempt=attempt + 1,
                status_code=api_response.status_code,
                duration_seconds=perf_counter() - started_at,
                response_bytes=len(api_response.content),
            )
            return api_response

        msg = f"{self._provider_name} request failed"
        raise ExternalServiceError(msg)

    def _validate_response(self, response: ApiResponse) -> ApiResponse:
        if response.status_code == HTTPStatus.TOO_MANY_REQUESTS or (
            response.status_code == HTTPStatus.FORBIDDEN and response.headers.get("x-ratelimit-remaining") == "0"
        ):
            logger.warning(
                "Provider rate limit exceeded", provider=self._provider_name, status_code=response.status_code
            )
            msg = f"{self._provider_name} rate limit exceeded"
            raise RateLimitError(msg)
        if response.status_code >= HTTPStatus.BAD_REQUEST:
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


def _validate_content_length(value: str | None, *, max_bytes: int) -> None:
    if value is None:
        return
    try:
        content_length = int(value)
    except ValueError:
        return
    if content_length > max_bytes:
        msg = f"provider response exceeds {max_bytes} bytes"
        raise _ResponseTooLargeError(msg)


def _can_retry(attempt: int) -> bool:
    return attempt < _MAX_RETRIES


async def _retry_transport_failure(
    attempt: int, context: dict[str, object], error: Exception, *, is_timeout: bool
) -> bool:
    if not _can_retry(attempt):
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


def optional_web_url(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return require_web_url(value)
    except ValueError:
        return None


async def fetch_languages(api: ApiClient, root: str, headers: Mapping[str, str]) -> tuple[str, ...]:
    response = await api.get_optional(f"{root}/languages", headers=headers)
    if response is None:
        return ()
    return await api.parse_payload(response, _parse_language_ranking)


def _parse_language_ranking(content: bytes) -> tuple[str, ...]:
    return _rank_language_items(_LANGUAGE_USAGE_ADAPTER.validate_json(content).items())


def _rank_language_items(languages: Iterable[tuple[str, int | float]]) -> tuple[str, ...]:
    return tuple(name for name, _ in sorted(languages, key=lambda item: (-item[1], item[0].casefold())))


def raise_task_group_error(error: ExceptionGroup[Exception], /) -> Never:
    for exception in _iter_group_exceptions(error):
        if isinstance(exception, (RepositoryAccessError, ValueError)):
            raise exception from error
    raise error


def _iter_group_exceptions(error: BaseExceptionGroup[BaseException]) -> Iterator[BaseException]:
    for exception in error.exceptions:
        if _is_base_exception_group(exception):
            yield from _iter_group_exceptions(exception)
        else:
            yield exception


def _is_base_exception_group(value: BaseException) -> TypeIs[BaseExceptionGroup[BaseException]]:
    return isinstance(value, BaseExceptionGroup)
