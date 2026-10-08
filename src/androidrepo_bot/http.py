from asyncio import sleep as async_sleep
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

import aiohttp

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

_READ_CHUNK_SIZE = 64 * 1024


class ResponseTooLargeError(ValueError):
    pass


async def read_bounded_response(response: aiohttp.ClientResponse, *, max_bytes: int, subject: str) -> bytes:
    _validate_content_length(response.headers.get("content-length"), max_bytes=max_bytes, subject=subject)
    content = bytearray()
    async for chunk in response.content.iter_chunked(_READ_CHUNK_SIZE):
        content.extend(chunk)
        if len(content) > max_bytes:
            msg = f"{subject} exceeds {max_bytes} bytes"
            raise ResponseTooLargeError(msg)
    return bytes(content)


def _validate_content_length(value: str | None, *, max_bytes: int, subject: str) -> None:
    if value is None:
        return
    try:
        content_length = int(value)
    except ValueError:
        return
    if content_length < 0 or content_length > max_bytes:
        msg = f"{subject} exceeds {max_bytes} bytes"
        raise ResponseTooLargeError(msg)


_READ_BUFFER_BYTES = 64 * 1024
_MAX_RESPONSE_HEADERS = 128
_MAX_HEADER_LINE_BYTES = 8 * 1024
_SSL_TRANSPORT_CLOSE_DELAY_SECONDS = 0.25


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
