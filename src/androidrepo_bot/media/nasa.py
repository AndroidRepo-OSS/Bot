from asyncio import timeout, to_thread
from secrets import choice
from time import perf_counter
from typing import Annotated, TypeIs
from urllib.parse import urlparse, urlunparse

import aiohttp
import structlog
from pydantic import BaseModel, BeforeValidator, ConfigDict, StringConstraints

from androidrepo_bot.media.models import SpaceArtwork

logger = structlog.get_logger(__name__)

_SEARCH_URL = "https://images-api.nasa.gov/search"
_ASSET_URL = "https://images-api.nasa.gov/asset/{identifier}"
_ALLOWED_ASSET_HOST = "images-assets.nasa.gov"
_TIMEOUT_SECONDS = 8.0
_MAX_METADATA_BYTES = 4 * 1024 * 1024
_MAX_IMAGE_BYTES = 12 * 1024 * 1024
_READ_CHUNK_SIZE = 64 * 1024
type _NonEmptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


def _blank_text_to_none(value: object) -> object:
    return None if isinstance(value, str) and not value.strip() else value


type _OptionalText = Annotated[_NonEmptyText | None, BeforeValidator(_blank_text_to_none)]


def _json_array_to_tuple(value: object) -> object:
    return tuple(value) if _is_object_list(value) else value


def _is_object_list(value: object) -> TypeIs[list[object]]:
    return isinstance(value, list)


type _JsonTuple[T] = Annotated[tuple[T, ...], BeforeValidator(_json_array_to_tuple)]


class _NasaModel(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)


class _SearchData(_NasaModel):
    nasa_id: _NonEmptyText
    title: _NonEmptyText
    center: _OptionalText = None
    date_created: _OptionalText = None


class _SearchLink(_NasaModel):
    rel: _OptionalText = None
    href: _OptionalText = None


class _SearchItem(_NasaModel):
    data: _JsonTuple[_SearchData]
    links: _JsonTuple[_SearchLink]


class _SearchCollection(_NasaModel):
    items: _JsonTuple[_SearchItem]


class _SearchPayload(_NasaModel):
    collection: _SearchCollection


class _AssetItem(_NasaModel):
    href: _OptionalText = None


class _AssetCollection(_NasaModel):
    items: _JsonTuple[_AssetItem]


class _AssetPayload(_NasaModel):
    collection: _AssetCollection


_CATALOG_IDENTIFIERS = (
    "PIA22085",
    "PIA22355",
    "PIA12966",
    "PIA13168",
    "PIA01884",
    "PIA16695",
    "PIA14730",
    "PIA25434",
    "PIA09108",
    "PIA25433",
    "PIA13442",
    "PIA13451",
    "PIA13128",
    "PIA13448",
    "PIA17553",
    "PIA14417",
    "PIA15658",
    "PIA07902",
    "PIA04200",
    "PIA05062",
    "PIA03606",
    "PIA09178",
    "PIA26601",
    "GSFC_20171208_Archive_e002172",
    "PIA23689",
    "PIA23690",
    "PIA04921",
    "PIA15656",
    "PIA04629",
    "PIA04624",
    "PIA08787",
    "PIA04630",
    "PIA07903",
    "PIA04628",
    "PIA04213",
    "PIA04218",
    "PIA07828",
)


async def fetch_nasa_artwork(session: aiohttp.ClientSession) -> SpaceArtwork | None:
    identifier = choice(_CATALOG_IDENTIFIERS)
    started_at = perf_counter()
    logger.debug("NASA artwork fetch started", nasa_id=identifier)
    try:
        artwork = await _fetch_artwork(session, identifier)
    except (TimeoutError, aiohttp.ClientError, KeyError, TypeError, ValueError) as error:
        logger.warning(
            "Could not load NASA banner artwork",
            nasa_id=identifier,
            duration_seconds=perf_counter() - started_at,
            error_type=type(error).__name__,
            exc_info=True,
        )
        return None
    logger.info(
        "NASA artwork fetched",
        nasa_id=artwork.identifier,
        duration_seconds=perf_counter() - started_at,
        image_bytes=len(artwork.content),
    )
    return artwork


async def _fetch_artwork(session: aiohttp.ClientSession, identifier: str) -> SpaceArtwork:
    search_content = await _read_metadata(session, _SEARCH_URL, params={"nasa_id": identifier, "media_type": "image"})
    search_payload = await to_thread(_SearchPayload.model_validate_json, search_content)
    item = _first_search_item(search_payload)
    metadata = _first_search_data(item)
    preview_url = _preview_url(item)
    if not _is_trusted_asset_url(preview_url):
        msg = "NASA preview URL uses an unexpected origin"
        raise ValueError(msg)

    resolved_identifier = metadata.nasa_id
    logger.debug("NASA artwork metadata fetched", nasa_id=resolved_identifier)
    asset_content = await _read_metadata(session, _ASSET_URL.format(identifier=resolved_identifier))
    asset_payload = await to_thread(_AssetPayload.model_validate_json, asset_content)
    candidates = tuple(dict.fromkeys((*_asset_urls(asset_payload), preview_url)))
    logger.debug("NASA artwork candidates resolved", nasa_id=resolved_identifier, candidate_count=len(candidates))
    content = await _download_first_image(session, candidates)
    center = metadata.center or "NASA"
    return SpaceArtwork(
        content=content,
        identifier=resolved_identifier,
        title=metadata.title,
        center=center,
        date_created=metadata.date_created,
        credit=_credit_for(center),
    )


async def _read_metadata(session: aiohttp.ClientSession, url: str, *, params: dict[str, str] | None = None) -> bytes:
    async with timeout(_TIMEOUT_SECONDS):
        async with session.get(url, headers={"User-Agent": "androidrepo-bot/space-banner"}, params=params) as response:
            response.raise_for_status()
            return await _read_bounded_response(response, max_bytes=_MAX_METADATA_BYTES, subject="NASA metadata")


async def _download_first_image(session: aiohttp.ClientSession, candidates: tuple[str, ...]) -> bytes:
    for url in candidates:
        parsed = urlparse(url)
        try:
            content = await _download_image(session, url)
        except (TimeoutError, aiohttp.ClientError, ValueError) as error:
            logger.debug(
                "NASA artwork image candidate rejected",
                asset_host=parsed.hostname,
                asset_path=parsed.path,
                error_type=type(error).__name__,
            )
            continue
        logger.debug(
            "NASA artwork image downloaded",
            asset_host=parsed.hostname,
            asset_path=parsed.path,
            image_bytes=len(content),
        )
        return content
    msg = "NASA did not provide a supported bounded image"
    raise ValueError(msg)


async def _download_image(session: aiohttp.ClientSession, url: str) -> bytes:
    if not _is_trusted_asset_url(url):
        msg = "NASA image URL uses an unexpected origin"
        raise ValueError(msg)

    async with timeout(_TIMEOUT_SECONDS):
        async with session.get(url, headers={"User-Agent": "androidrepo-bot/space-banner"}) as response:
            response.raise_for_status()
            content_type = response.headers.get("content-type", "")
            if not content_type.startswith("image/"):
                msg = "NASA image is not a supported bounded image"
                raise ValueError(msg)
            return await _read_bounded_response(response, max_bytes=_MAX_IMAGE_BYTES, subject="NASA image")


def _first_search_item(payload: object) -> _SearchItem:
    root = payload if isinstance(payload, _SearchPayload) else _SearchPayload.model_validate(payload)
    if not root.collection.items:
        msg = "NASA search returned no matching image"
        raise ValueError(msg)
    return root.collection.items[0]


def _first_search_data(item: _SearchItem) -> _SearchData:
    if not item.data:
        msg = "NASA search item data is empty"
        raise ValueError(msg)
    return item.data[0]


def _preview_url(item: _SearchItem) -> str:
    for link in item.links:
        if link.rel == "preview" and link.href is not None:
            return link.href
    msg = "NASA item has no preview link"
    raise ValueError(msg)


def _asset_urls(payload: object) -> tuple[str, ...]:
    root = payload if isinstance(payload, _AssetPayload) else _AssetPayload.model_validate(payload)
    ranked: list[tuple[int, str]] = []
    for item in root.collection.items:
        if item.href is None:
            continue
        url = _normalize_asset_url(item.href)
        if url is None:
            continue
        path = urlparse(url).path.casefold()
        if not path.endswith((".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff")):
            continue
        if "~orig." in path:
            rank = 0
        elif "~large." in path:
            rank = 1
        elif "~medium." in path:
            rank = 2
        else:
            rank = 3
        ranked.append((rank, url))
    return tuple(url for _, url in sorted(ranked))


def _normalize_asset_url(value: str) -> str | None:
    parsed = urlparse(value)
    if (
        parsed.hostname != _ALLOWED_ASSET_HOST
        or parsed.scheme not in {"http", "https"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port is not None
    ):
        return None
    return urlunparse(parsed._replace(scheme="https"))


async def _read_bounded_response(response: aiohttp.ClientResponse, *, max_bytes: int, subject: str) -> bytes:
    _validate_content_length(response.headers.get("content-length"), max_bytes=max_bytes, subject=subject)
    content = bytearray()
    async for chunk in response.content.iter_chunked(_READ_CHUNK_SIZE):
        content.extend(chunk)
        if len(content) > max_bytes:
            msg = f"{subject} exceeds {max_bytes} bytes"
            raise ValueError(msg)
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
        raise ValueError(msg)


def _is_trusted_asset_url(value: str) -> bool:
    parsed = urlparse(value)
    return (
        parsed.scheme == "https"
        and parsed.hostname == _ALLOWED_ASSET_HOST
        and parsed.username is None
        and parsed.password is None
        and parsed.port is None
    )


def _credit_for(center: str) -> str:
    normalized = center.casefold()
    if normalized == "jpl":
        return "NASA/JPL-Caltech"
    if normalized == "gsfc":
        return "NASA/GSFC"
    if normalized == "jsc":
        return "NASA/JSC"
    return f"NASA/{center}"
