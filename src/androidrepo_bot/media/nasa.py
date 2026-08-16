from asyncio import timeout, to_thread
from dataclasses import dataclass
from http import HTTPStatus
from secrets import choice
from time import perf_counter
from typing import TYPE_CHECKING, Annotated
from urllib.parse import SplitResult, urlsplit, urlunsplit

import aiohttp
import structlog
from pydantic import BaseModel, ConfigDict, StringConstraints, ValidationError

from androidrepo_bot.http import ResponseTooLargeError, read_bounded_response
from androidrepo_bot.media.models import SpaceArtwork

logger = structlog.get_logger(__name__)

if TYPE_CHECKING:
    from collections.abc import Mapping

_SEARCH_URL = "https://images-api.nasa.gov/search"
_ASSET_URL = "https://images-api.nasa.gov/asset/{identifier}"
_ALLOWED_ASSET_HOST = "images-assets.nasa.gov"
_TIMEOUT_SECONDS = 8.0
_ARTWORK_TIMEOUT_SECONDS = 20.0
_MAX_METADATA_BYTES = 4 * 1024 * 1024
_MAX_IMAGE_BYTES = 12 * 1024 * 1024
_MAX_IMAGE_CANDIDATES = 8
_REQUEST_TIMEOUT = aiohttp.ClientTimeout(
    total=_TIMEOUT_SECONDS, connect=5.0, sock_connect=5.0, sock_read=_TIMEOUT_SECONDS
)
_REQUEST_HEADERS = {"User-Agent": "androidrepo-bot/space-banner"}
_JSON_CONTENT_TYPES = frozenset({"application/json"})
_IMAGE_CONTENT_TYPES = frozenset({"image/jpeg", "image/png", "image/tiff", "image/webp"})
type _Identifier = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
type _Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
type _Center = Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)]
type _Date = Annotated[str, StringConstraints(strip_whitespace=True, max_length=100)]
type _Relation = Annotated[str, StringConstraints(strip_whitespace=True, max_length=50)]
type _Url = Annotated[str, StringConstraints(strip_whitespace=True, max_length=2_048)]


class NasaArtworkError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class _ResponsePolicy:
    subject: str
    max_bytes: int
    allowed_content_types: frozenset[str]


_METADATA_POLICY = _ResponsePolicy("NASA metadata", _MAX_METADATA_BYTES, _JSON_CONTENT_TYPES)
_IMAGE_POLICY = _ResponsePolicy("NASA image", _MAX_IMAGE_BYTES, _IMAGE_CONTENT_TYPES)


class _NasaModel(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)


class _SearchData(_NasaModel):
    nasa_id: _Identifier
    title: _Title
    center: _Center | None = None
    date_created: _Date | None = None


class _SearchLink(_NasaModel):
    rel: _Relation | None = None
    href: _Url | None = None


class _SearchItem(_NasaModel):
    data: tuple[_SearchData, ...]
    links: tuple[_SearchLink, ...]


class _SearchCollection(_NasaModel):
    items: tuple[_SearchItem, ...]


class _SearchPayload(_NasaModel):
    collection: _SearchCollection


class _AssetItem(_NasaModel):
    href: _Url | None = None


class _AssetCollection(_NasaModel):
    items: tuple[_AssetItem, ...]


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
        async with timeout(_ARTWORK_TIMEOUT_SECONDS):
            artwork = await _fetch_artwork(session, identifier)
    except (TimeoutError, aiohttp.ClientError, NasaArtworkError, ResponseTooLargeError, ValidationError) as error:
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
    metadata, preview_url = _search_result(search_payload)
    if metadata.nasa_id != identifier:
        msg = "NASA search returned an unexpected artwork identifier"
        raise NasaArtworkError(msg)
    if not _is_trusted_asset_url(preview_url):
        msg = "NASA preview URL uses an unexpected origin"
        raise NasaArtworkError(msg)

    resolved_identifier = metadata.nasa_id
    logger.debug("NASA artwork metadata fetched", nasa_id=resolved_identifier)
    asset_content = await _read_metadata(session, _ASSET_URL.format(identifier=resolved_identifier))
    asset_urls = await to_thread(parse_nasa_asset_urls, asset_content)
    candidates = tuple(dict.fromkeys((*asset_urls, preview_url)))[:_MAX_IMAGE_CANDIDATES]
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
    return await _read_response(session, url, policy=_METADATA_POLICY, params=params)


async def _download_first_image(session: aiohttp.ClientSession, candidates: tuple[str, ...]) -> bytes:
    for url in candidates:
        parsed = _safe_urlsplit(url)
        asset_host: str | None = None
        asset_path: str | None = None
        if parsed is not None:
            asset_host = parsed.hostname
            asset_path = parsed.path
        try:
            content = await _download_image(session, url)
        except (TimeoutError, aiohttp.ClientError, NasaArtworkError, ResponseTooLargeError) as error:
            logger.debug(
                "NASA artwork image candidate rejected",
                asset_host=asset_host,
                asset_path=asset_path,
                error_type=type(error).__name__,
            )
            continue
        logger.debug(
            "NASA artwork image downloaded", asset_host=asset_host, asset_path=asset_path, image_bytes=len(content)
        )
        return content
    msg = "NASA did not provide a supported bounded image"
    raise NasaArtworkError(msg)


async def _download_image(session: aiohttp.ClientSession, url: str) -> bytes:
    if not _is_trusted_asset_url(url):
        msg = "NASA image URL uses an unexpected origin"
        raise NasaArtworkError(msg)

    return await _read_response(session, url, policy=_IMAGE_POLICY)


async def _read_response(
    session: aiohttp.ClientSession, url: str, *, policy: _ResponsePolicy, params: Mapping[str, str] | None = None
) -> bytes:
    async with session.get(
        url, headers=_REQUEST_HEADERS, params=params, allow_redirects=False, timeout=_REQUEST_TIMEOUT
    ) as response:
        _require_success(response, subject=policy.subject)
        if response.content_type.casefold() not in policy.allowed_content_types:
            msg = f"{policy.subject} returned an unsupported content type"
            raise NasaArtworkError(msg)
        return await read_bounded_response(response, max_bytes=policy.max_bytes, subject=policy.subject)


def _require_success(response: aiohttp.ClientResponse, *, subject: str) -> None:
    if HTTPStatus.OK <= response.status < HTTPStatus.MULTIPLE_CHOICES:
        return
    if response.status >= HTTPStatus.BAD_REQUEST:
        response.raise_for_status()
    msg = f"{subject} returned HTTP {response.status}"
    raise NasaArtworkError(msg)


def _search_result(payload: _SearchPayload) -> tuple[_SearchData, str]:
    if not payload.collection.items:
        msg = "NASA search returned no matching image"
        raise NasaArtworkError(msg)
    item = payload.collection.items[0]
    if not item.data:
        msg = "NASA search item data is empty"
        raise NasaArtworkError(msg)
    metadata = item.data[0]
    for link in item.links:
        if link.rel == "preview" and link.href:
            return metadata, link.href
    msg = "NASA item has no preview link"
    raise NasaArtworkError(msg)


def parse_nasa_asset_urls(content: bytes) -> tuple[str, ...]:
    payload = _AssetPayload.model_validate_json(content)
    ranked: list[tuple[int, str]] = []
    for item in payload.collection.items:
        if not item.href:
            continue
        url = _normalize_asset_url(item.href)
        if url is None:
            continue
        path = urlsplit(url).path.casefold()
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
    parsed = _safe_urlsplit(value)
    if parsed is None:
        return None
    if parsed.scheme not in {"http", "https"} or not _has_trusted_authority(parsed):
        return None
    return urlunsplit(parsed._replace(scheme="https"))


def _is_trusted_asset_url(value: str) -> bool:
    parsed = _safe_urlsplit(value)
    return parsed is not None and parsed.scheme == "https" and _has_trusted_authority(parsed)


def _safe_urlsplit(value: str) -> SplitResult | None:
    try:
        return urlsplit(value)
    except ValueError:
        return None


def _has_trusted_authority(parsed: SplitResult) -> bool:
    try:
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.hostname == _ALLOWED_ASSET_HOST and parsed.username is None and parsed.password is None and port is None
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
