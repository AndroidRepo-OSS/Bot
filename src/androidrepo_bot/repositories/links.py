import html
import re
from asyncio import to_thread
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import TYPE_CHECKING, override
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit

from androidrepo_bot.repositories.models import RepositoryLink

if TYPE_CHECKING:
    from collections.abc import Collection, Iterable

_REFERENCE_DEFINITION = re.compile(
    r"""(?mx)
    ^[ \t]{0,3}\[([^\]\n]+)\]:[ \t]*(?:<([^>\n]+)>|(\S+))
    (?:[ \t]+(?:"[^"\n]*"|'[^'\n]*'|\([^\)\n]*\)))?[ \t]*$
    """
)
_AUTOLINK = re.compile(r"<(https?://[^<>\s]+)>", re.IGNORECASE)
_BARE_URL = re.compile(r"""(?<![\w@])https?://[^\s<>"']+""", re.IGNORECASE)
_HTML_TAG = re.compile(r"<[^>]+>")
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_INLINE_CODE = re.compile(r"(`+)(.*?)\1", re.DOTALL)
_FENCE = re.compile(r"^[ \t]{0,3}(`{3,}|~{3,})")
_CLOSING_FENCE = re.compile(r"^[ \t]{0,3}(`+|~+)[ \t]*$")
_HTML_TAG_LABEL = re.compile(r"<[^>]+>")
_MARKDOWN_ESCAPE = re.compile(r"\\([\\`*{}\[\]()#+\-.!_>~|])")
_MARKDOWN_IMAGE = re.compile(r"!\[([^\]]*)\]\([^\)]*\)")
_WHITESPACE = re.compile(r"\s+")


@dataclass(frozen=True, slots=True)
class LinkCandidate:
    position: int
    label: str
    destination: str


@dataclass(slots=True)
class _OpenAnchor:
    position: int
    destination: str
    label_parts: list[str]


class _AnchorParser(HTMLParser):
    def __init__(self, source: str) -> None:
        super().__init__(convert_charrefs=True)
        self.candidates: list[LinkCandidate] = []
        self._line_offsets = _line_offsets(source)
        self._anchors: list[_OpenAnchor] = []

    @override
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag.casefold() == "a" and (destination := attributes.get("href")):
            line, column = self.getpos()
            self._anchors.append(_OpenAnchor(self._line_offsets[line - 1] + column, destination, []))
        elif tag.casefold() == "img" and self._anchors and (alt := attributes.get("alt")):
            self._anchors[-1].label_parts.append(alt)

    @override
    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() != "a":
            self.handle_starttag(tag, attrs)
            return
        attributes = dict(attrs)
        if not (destination := attributes.get("href")):
            return
        line, column = self.getpos()
        self.candidates.append(
            LinkCandidate(
                self._line_offsets[line - 1] + column,
                attributes.get("aria-label") or attributes.get("title") or "",
                destination,
            )
        )

    @override
    def handle_data(self, data: str) -> None:
        if self._anchors:
            self._anchors[-1].label_parts.append(data)

    @override
    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() == "a" and self._anchors:
            self._finalize_anchor(self._anchors.pop())

    @override
    def close(self) -> None:
        super().close()
        while self._anchors:
            self._finalize_anchor(self._anchors.pop())

    def _finalize_anchor(self, anchor: _OpenAnchor) -> None:
        self.candidates.append(LinkCandidate(anchor.position, " ".join(anchor.label_parts), anchor.destination))


def extract_candidates(readme: str) -> list[LinkCandidate]:
    visible = _mask_non_content(readme)
    html_parser = _AnchorParser(visible)
    html_parser.feed(visible)
    html_parser.close()

    references, definition_ranges = _reference_definitions(visible)
    visible = _mask_ranges(visible, definition_ranges)
    markdown, markdown_ranges = _markdown_links(visible, references)
    plain = _mask_ranges(visible, markdown_ranges)
    autolinks = list(_AUTOLINK.finditer(plain))
    bare = _mask_matches(plain, autolinks)
    bare = _mask_matches(bare, _HTML_TAG.finditer(bare))

    candidates = [
        *html_parser.candidates,
        *markdown,
        *(LinkCandidate(match.start(), match.group(1), match.group(1)) for match in autolinks),
        *(
            LinkCandidate(match.start(), match.group(0), _trim_bare_url(match.group(0)))
            for match in _BARE_URL.finditer(bare)
        ),
    ]
    candidates.sort(key=lambda candidate: candidate.position)
    return candidates


def _reference_definitions(source: str) -> tuple[dict[str, str], list[tuple[int, int]]]:
    references: dict[str, str] = {}
    ranges: list[tuple[int, int]] = []
    for match in _REFERENCE_DEFINITION.finditer(source):
        references[_reference_key(match.group(1))] = match.group(2) or match.group(3)
        ranges.append(match.span())
    return references, ranges


def _markdown_links(source: str, references: dict[str, str]) -> tuple[list[LinkCandidate], list[tuple[int, int]]]:
    candidates: list[LinkCandidate] = []
    ranges: list[tuple[int, int]] = []
    index = 0
    while index < len(source):
        if source[index] != "[" or (index > 0 and source[index - 1] == "\\"):
            index += 1
            continue
        is_image = index > 0 and source[index - 1] == "!"
        syntax_start = index - 1 if is_image else index
        label_end = _closing_delimiter(source, index, "[", "]")
        if label_end is None:
            index += 1
            continue

        label = source[index + 1 : label_end]
        destination_start = _skip_spaces(source, label_end + 1)
        destination: str | None = None
        link_end = label_end
        if destination_start < len(source) and source[destination_start] == "(":
            destination_end = _closing_delimiter(source, destination_start, "(", ")")
            if destination_end is not None:
                destination = _inline_destination(source[destination_start + 1 : destination_end])
                link_end = destination_end
        elif destination_start < len(source) and source[destination_start] == "[":
            reference_end = _closing_delimiter(source, destination_start, "[", "]")
            if reference_end is not None:
                reference = source[destination_start + 1 : reference_end] or label
                destination = references.get(_reference_key(reference))
                link_end = reference_end
        else:
            destination = references.get(_reference_key(label))

        if not destination:
            index = label_end + 1
            continue
        ranges.append((syntax_start, link_end + 1))
        if not is_image:
            candidates.append(LinkCandidate(index, label, destination))
        index = link_end + 1
    return candidates, ranges


def _closing_delimiter(source: str, start: int, opening: str, closing: str) -> int | None:
    depth = 0
    escaped = False
    for index in range(start, len(source)):
        character = source[index]
        if escaped:
            escaped = False
        elif character == "\\":
            escaped = True
        elif character == opening:
            depth += 1
        elif character == closing:
            depth -= 1
            if depth == 0:
                return index
        elif character == "\n" and opening == "(":
            return None
    return None


def _inline_destination(value: str) -> str | None:
    value = value.strip()
    if not value:
        return None
    if value.startswith("<"):
        closing = value.find(">")
        return value[1:closing] if closing > 0 else None
    depth = 0
    escaped = False
    for index, character in enumerate(value):
        if escaped:
            escaped = False
        elif character == "\\":
            escaped = True
        elif character == "(":
            depth += 1
        elif character == ")" and depth:
            depth -= 1
        elif character.isspace() and depth == 0:
            return value[:index]
    return value


def _reference_key(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip()).casefold()


def _skip_spaces(source: str, start: int) -> int:
    while start < len(source) and source[start] in {" ", "\t"}:
        start += 1
    return start


def _trim_bare_url(url: str) -> str:
    url = url.rstrip(".,;:!?")
    pairs = {")": "(", "]": "[", "}": "{"}
    while url and (opening := pairs.get(url[-1])) and url.count(url[-1]) > url.count(opening):
        url = url[:-1]
    return url


def _mask_non_content(source: str) -> str:
    source = _mask_matches(source, _HTML_COMMENT.finditer(source))
    source = _mask_fenced_code(source)
    return _mask_matches(source, _INLINE_CODE.finditer(source))


def _mask_fenced_code(source: str) -> str:
    lines = source.splitlines(keepends=True)
    fence_character: str | None = None
    fence_length = 0
    for index, line in enumerate(lines):
        if fence_character is None:
            if (match := _FENCE.match(line)) is None:
                continue
            fence = match.group(1)
            fence_character = fence[0]
            fence_length = len(fence)
            lines[index] = _masked(line)
            continue
        lines[index] = _masked(line)
        match = _CLOSING_FENCE.match(line.rstrip("\r\n"))
        if match and match.group(1)[0] == fence_character and len(match.group(1)) >= fence_length:
            fence_character = None
            fence_length = 0
    return "".join(lines)


def _mask_ranges(source: str, ranges: list[tuple[int, int]]) -> str:
    characters = list(source)
    for start, end in ranges:
        characters[start:end] = _masked(source[start:end])
    return "".join(characters)


def _mask_matches(source: str, matches: Iterable[re.Match[str]]) -> str:
    return _mask_ranges(source, [match.span() for match in matches])


def _masked(value: str) -> str:
    return "".join(character if character in {"\n", "\r"} else " " for character in value)


def _line_offsets(source: str) -> list[int]:
    return [0, *(match.end() for match in re.finditer(r"\n", source))]


async def build_repository_links(
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
            await to_thread(
                _readme_links, repository_url, readme, readme_url=readme_url, known_urls={link.url for link in links}
            )
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
    return found


def _resolve_url(destination: str, *, repository_url: str, readme_url: str | None) -> str | None:
    destination = html.unescape(_MARKDOWN_ESCAPE.sub(r"\1", destination.strip()))
    if not destination:
        return None
    if destination.startswith("#"):
        resolved = f"{repository_url.rstrip('/')}{destination}"
    else:
        resolved = urljoin(readme_url or _fallback_readme_url(repository_url), destination)
    try:
        parsed = urlsplit(resolved)
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme.casefold() not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or port == 0
    ):
        return None
    return urlunsplit((parsed.scheme.casefold(), parsed.netloc.casefold(), parsed.path, parsed.query, parsed.fragment))


def _fallback_readme_url(repository_url: str) -> str:
    host = urlsplit(repository_url).netloc.casefold()
    root = repository_url.rstrip("/")
    if host == "github.com":
        return f"{root}/blob/HEAD/README.md"
    if host == "gitlab.com":
        return f"{root}/-/blob/HEAD/README.md"
    return f"{root}/README.md"


def _clean_label(label: str, url: str) -> str:
    label = _MARKDOWN_IMAGE.sub(r"\1", label)
    label = _HTML_TAG_LABEL.sub(" ", label)
    label = html.unescape(_MARKDOWN_ESCAPE.sub(r"\1", label))
    label = _WHITESPACE.sub(" ", label.strip(" *_~`|"))
    if not label or label.casefold().startswith(("http://", "https://")):
        label = _label_from_url(url)
    maximum_length = 120
    if len(label) > maximum_length:
        return f"{label[: maximum_length - 3].rstrip()}..."
    return label


def _label_from_url(url: str) -> str:
    parsed = urlsplit(url)
    path = unquote(parsed.path).rstrip("/")
    suffix = path.rsplit("/", 1)[-1] if path else ""
    return f"{parsed.netloc}/{suffix}" if suffix else parsed.netloc


def _url_key(url: str) -> tuple[str, str, str, str, str]:
    parsed = urlsplit(url)
    return (
        parsed.scheme.casefold(),
        parsed.netloc.casefold(),
        parsed.path.rstrip("/") or "/",
        parsed.query,
        parsed.fragment,
    )
