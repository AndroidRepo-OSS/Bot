import html
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import TYPE_CHECKING, override
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit

from androidrepo_bot.repositories.models import RepositoryLink, require_web_url

if TYPE_CHECKING:
    from collections.abc import Collection

_REFERENCE = re.compile(r"(?m)^\s{0,3}\[([^\[\]\n]{1,120})\]:\s*<?([^\s>\[]{1,2048})>?[^\n]{0,500}$")
_BADGE_LINK = re.compile(
    r"\[!\[([^\[\]\n]{0,120})]\((?:<[^<>\n]{1,2048}>|[^\s)\[]{1,2048})\)]"
    r"\((?:<([^<>\n]{1,2048})>|([^\s)\[]{1,2048}))\)"
)
_MARKDOWN_LINK = re.compile(
    r"(?<!!)\[(?!!)([^\[\]\n]{1,120})]"
    r"\((?:<([^<>\n]{1,2048})>|([^\s)\[]{1,2048}))"
    r"(?:\s+(?:\"[^\"\n\[]{0,500}\"|'[^'\n\[]{0,500}'))?\)"
)
_REFERENCE_LINK = re.compile(r"(?<!!)\[([^\[\]\n]{1,120})]\[([^\[\]\n]{0,120})]")
_MARKDOWN_IMAGE = re.compile(
    r"!\[[^\[\]\n]{0,120}]"
    r"\((?:<[^<>\n]{1,2048}>|[^\s)\[]{1,2048})"
    r"(?:\s+(?:\"[^\"\n\[]{0,500}\"|'[^'\n\[]{0,500}'))?\)"
)
_REFERENCE_IMAGE = re.compile(r"!\[[^\[\]\n]{0,120}]\[[^\[\]\n]{0,120}]")
_AUTOLINK = re.compile(r"<(https?://[^<>\s\[]{1,2048})>", re.IGNORECASE)
_BARE_URL = re.compile(r"(?<![\w@])https?://[^\s<>\"'\[]{1,2048}", re.IGNORECASE)
_HTML_TAG = re.compile(r"<[^<>\n]{1,2048}>")
_MARKDOWN_ESCAPE = re.compile(r"\\([\\`*{}\[\]()#+\-.!_>~|])")
_WHITESPACE = re.compile(r"\s+")
_README_SCAN_LIMIT = 50_000
_MAX_LABEL_LENGTH = 120
_MAX_README_LINKS = 20
_MAX_MARKDOWN_INDENT = 3
_MIN_FENCE_LENGTH = 3


@dataclass(frozen=True, slots=True)
class LinkCandidate:
    position: int
    label: str
    destination: str


class _AnchorParser(HTMLParser):
    def __init__(self, source: str) -> None:
        super().__init__(convert_charrefs=True)
        self.candidates: list[LinkCandidate] = []
        self._line_offsets = [0, *(match.end() for match in re.finditer(r"\n", source))]
        self._anchor: tuple[int, str, list[str]] | None = None

    @override
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag.casefold() == "a" and (destination := attributes.get("href")):
            line, column = self.getpos()
            self._anchor = (self._line_offsets[line - 1] + column, destination, [])
        elif tag.casefold() == "img" and self._anchor is not None and (alt := attributes.get("alt")):
            self._anchor[2].append(alt)

    @override
    def handle_data(self, data: str) -> None:
        if self._anchor is not None:
            self._anchor[2].append(data)

    @override
    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() != "a" or self._anchor is None:
            return
        position, destination, label = self._anchor
        self.candidates.append(LinkCandidate(position, " ".join(label), destination))
        self._anchor = None


def extract_candidates(readme: str) -> list[LinkCandidate]:
    visible = _mask_code_and_comments(readme[:_README_SCAN_LIMIT])
    references = {_reference_key(match.group(1)): match.group(2) for match in _REFERENCE.finditer(visible)}
    candidates = [
        *(
            LinkCandidate(match.start(), match.group(1), match.group(2) or match.group(3))
            for match in _BADGE_LINK.finditer(visible)
        ),
        *(
            LinkCandidate(match.start(), match.group(1), match.group(2) or match.group(3))
            for match in _MARKDOWN_LINK.finditer(visible)
        ),
        *(
            LinkCandidate(match.start(), match.group(1), destination)
            for match in _REFERENCE_LINK.finditer(visible)
            if (destination := references.get(_reference_key(match.group(2) or match.group(1))))
        ),
        *(LinkCandidate(match.start(), match.group(1), match.group(1)) for match in _AUTOLINK.finditer(visible)),
    ]

    parser = _AnchorParser(visible)
    parser.feed(visible)
    candidates.extend(parser.candidates)

    plain = visible
    for pattern in (
        _BADGE_LINK,
        _MARKDOWN_LINK,
        _REFERENCE_LINK,
        _MARKDOWN_IMAGE,
        _REFERENCE_IMAGE,
        _REFERENCE,
        _AUTOLINK,
    ):
        plain = pattern.sub(lambda match: _masked(match.group()), plain)
    plain = _HTML_TAG.sub(lambda match: _masked(match.group()), plain)
    candidates.extend(
        LinkCandidate(match.start(), match.group(), _trim_bare_url(match.group()))
        for match in _BARE_URL.finditer(plain)
    )
    candidates.sort(key=lambda candidate: candidate.position)
    return candidates


def build_repository_links(
    repository_url: str,
    *,
    release_url: str | None,
    homepage: str | None,
    readme: str | None,
    readme_url: str | None = None,
) -> tuple[RepositoryLink, ...]:
    links = [RepositoryLink(id="repository", label="Repository", url=repository_url)]
    if release_url:
        links.append(RepositoryLink(id="release", label="Latest release", url=release_url))
    if homepage and _url_key(homepage) != _url_key(repository_url):
        links.append(RepositoryLink(id="website", label="Website", url=homepage))
    if readme:
        links.extend(
            _readme_links(repository_url, readme, readme_url=readme_url, known_urls={link.url for link in links})
        )
    return tuple(links)


def _readme_links(
    repository_url: str, readme: str, *, readme_url: str | None, known_urls: Collection[str]
) -> list[RepositoryLink]:
    known_keys = {_url_key(url) for url in known_urls}
    found: list[RepositoryLink] = []
    for candidate in extract_candidates(readme):
        url = _resolve_url(candidate.destination, repository_url=repository_url, readme_url=readme_url)
        if url is None or (key := _url_key(url)) in known_keys:
            continue
        try:
            link = RepositoryLink(id=f"readme-{len(found) + 1}", label=_clean_label(candidate.label, url), url=url)
        except ValueError:
            continue
        known_keys.add(key)
        found.append(link)
        if len(found) == _MAX_README_LINKS:
            break
    return found


def _resolve_url(destination: str, *, repository_url: str, readme_url: str | None) -> str | None:
    destination = html.unescape(_MARKDOWN_ESCAPE.sub(r"\1", destination.strip()))
    if not destination:
        return None
    resolved = (
        f"{repository_url.rstrip('/')}{destination}"
        if destination.startswith("#")
        else urljoin(readme_url or _fallback_readme_url(repository_url), destination)
    )
    try:
        parsed = urlsplit(require_web_url(resolved))
    except ValueError:
        return None
    return urlunsplit((parsed.scheme.casefold(), parsed.netloc.casefold(), parsed.path, parsed.query, parsed.fragment))


def _fallback_readme_url(repository_url: str) -> str:
    root = repository_url.rstrip("/")
    return f"{root}/-/blob/HEAD/README.md" if urlsplit(root).hostname == "gitlab.com" else f"{root}/blob/HEAD/README.md"


def _clean_label(label: str, url: str) -> str:
    label = html.unescape(_MARKDOWN_ESCAPE.sub(r"\1", _HTML_TAG.sub(" ", label)))
    label = _WHITESPACE.sub(" ", label.strip(" *_~`|"))
    if not label or label.casefold().startswith(("http://", "https://")):
        parsed = urlsplit(url)
        path_name = unquote(parsed.path).rstrip("/").rsplit("/", 1)[-1]
        label = f"{parsed.netloc}/{path_name}" if path_name else parsed.netloc
    return f"{label[: _MAX_LABEL_LENGTH - 3].rstrip()}..." if len(label) > _MAX_LABEL_LENGTH else label


def _mask_code_and_comments(source: str) -> str:
    source = _mask_html_comments(source)
    source = _mask_fenced_code(source)
    return _mask_inline_code(source)


def _mask_html_comments(source: str) -> str:
    parts: list[str] = []
    cursor = 0
    while (start := source.find("<!--", cursor)) >= 0:
        parts.append(source[cursor:start])
        end = source.find("-->", start + 4)
        if end < 0:
            parts.append(_masked(source[start:]))
            return "".join(parts)
        end += 3
        parts.append(_masked(source[start:end]))
        cursor = end
    parts.append(source[cursor:])
    return "".join(parts)


def _mask_fenced_code(source: str) -> str:
    lines = source.splitlines(keepends=True)
    fence_character: str | None = None
    fence_length = 0
    for index, line in enumerate(lines):
        content = line.rstrip("\r\n")
        candidate = content.lstrip(" \t")
        indentation = len(content) - len(candidate)
        marker_length = (
            len(candidate) - len(candidate.lstrip(candidate[0]))
            if indentation <= _MAX_MARKDOWN_INDENT and candidate and candidate[0] in "`~"
            else 0
        )

        if fence_character is None:
            if marker_length < _MIN_FENCE_LENGTH:
                continue
            fence_character = candidate[0]
            fence_length = marker_length
            lines[index] = _masked(line)
            continue

        lines[index] = _masked(line)
        if marker_length >= fence_length and candidate[0] == fence_character and not candidate[marker_length:].strip():
            fence_character = None
            fence_length = 0
    return "".join(lines)


def _mask_inline_code(source: str) -> str:
    characters = list(source)
    cursor = 0
    while (start := source.find("`", cursor)) >= 0:
        delimiter_end = start + 1
        while delimiter_end < len(source) and source[delimiter_end] == "`":
            delimiter_end += 1
        delimiter = source[start:delimiter_end]
        end = source.find(delimiter, delimiter_end)
        if end < 0:
            cursor = delimiter_end
            continue
        end += len(delimiter)
        characters[start:end] = _masked(source[start:end])
        cursor = end
    return "".join(characters)


def _masked(value: str) -> str:
    return "".join(character if character in {"\n", "\r"} else " " for character in value)


def _reference_key(value: str) -> str:
    return _WHITESPACE.sub(" ", value.strip()).casefold()


def _trim_bare_url(url: str) -> str:
    return url.rstrip(".,;:!?)]}")


def _url_key(url: str) -> tuple[str, str, str, str, str]:
    parsed = urlsplit(url)
    return (
        parsed.scheme.casefold(),
        parsed.netloc.casefold(),
        parsed.path.rstrip("/") or "/",
        parsed.query,
        parsed.fragment,
    )
