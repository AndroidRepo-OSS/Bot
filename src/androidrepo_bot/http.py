from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import aiohttp

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
