import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import TYPE_CHECKING, override
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit

from markdown_it import MarkdownIt

from androidrepo_bot.repositories.models import RepositoryLink, RepositoryLinkKind, require_web_url, web_url_key

if TYPE_CHECKING:
    from collections.abc import Collection

_BARE_URL = re.compile(r"(?<![\w@])https?://[^\s<>\"'\[]{1,2048}", re.IGNORECASE)
_WHITESPACE = re.compile(r"\s+")
_README_SCAN_LIMIT = 50_000
_MAX_LABEL_LENGTH = 120
_MAX_README_LINKS = 20
_HIDDEN_TAGS = frozenset({"code", "pre", "script", "style", "textarea", "template"})
_DOCUMENTATION_TERMS = frozenset({"docs", "documentation", "guide", "manual", "wiki"})
_SUPPORT_TERMS = frozenset({"help", "issues", "support"})
_DONATION_TERMS = frozenset({"donate", "donation", "fund", "sponsor", "sponsors"})
_RELEASE_PATHS = {
    "github.com": re.compile(r"/[^/]+/[^/]+/releases(?:/|$)"),
    "gitlab.com": re.compile(r"/(?:[^/]+/){2,}-/releases(?:/|$)"),
}


@dataclass(frozen=True, slots=True)
class _LinkCandidate:
    label: str
    destination: str


class _ReadmeLinkParser(HTMLParser):
    """Inspect rendered markup without loading URLs or treating image sources as links."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.candidates: list[_LinkCandidate] = []
        self._anchor: tuple[str, list[str]] | None = None
        self._hidden_depth = 0

    @override
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _HIDDEN_TAGS:
            self._hidden_depth += 1
        if self._hidden_depth:
            return
        attributes = dict(attrs)
        if tag == "a" and (destination := attributes.get("href")):
            self._anchor = (destination, [])
        elif tag == "img" and self._anchor is not None and (alt := attributes.get("alt")):
            self._anchor[1].append(alt)

    @override
    def handle_data(self, data: str) -> None:
        if self._hidden_depth:
            return
        if self._anchor is not None:
            self._anchor[1].append(data)
            return
        self.candidates.extend(
            _LinkCandidate(match.group(), _trim_bare_url(match.group())) for match in _BARE_URL.finditer(data)
        )

    @override
    def handle_endtag(self, tag: str) -> None:
        if tag in _HIDDEN_TAGS and self._hidden_depth:
            self._hidden_depth -= 1
            return
        if self._hidden_depth or tag != "a" or self._anchor is None:
            return
        destination, label = self._anchor
        self.candidates.append(_LinkCandidate("".join(label), destination))
        self._anchor = None


def _extract_candidates(readme: str) -> list[_LinkCandidate]:
    # CommonMark handles references, nested labels, escapes, and code blocks.
    # The HTML stays in memory and is only parsed; no browser or renderer executes it.
    rendered = MarkdownIt("commonmark").render(readme[:_README_SCAN_LIMIT])
    parser = _ReadmeLinkParser()
    parser.feed(rendered)
    parser.close()
    return parser.candidates


def build_repository_links(
    repository_url: str,
    *,
    release_url: str | None,
    homepage: str | None,
    readme: str | None,
    readme_url: str | None = None,
) -> tuple[RepositoryLink, ...]:
    links = [
        RepositoryLink(id="repository", label="Repository", url=repository_url, kind=RepositoryLinkKind.REPOSITORY)
    ]
    known_keys = {web_url_key(repository_url)}
    for link_id, label, url, kind in (
        ("release", "Latest release", release_url, RepositoryLinkKind.RELEASE),
        ("website", "Website", homepage, RepositoryLinkKind.WEBSITE),
    ):
        if url and (key := web_url_key(url)) not in known_keys:
            links.append(RepositoryLink(id=link_id, label=label, url=url, kind=kind))
            known_keys.add(key)
    if readme:
        links.extend(
            _readme_links(repository_url, readme, readme_url=readme_url, known_urls={link.url for link in links})
        )
    return tuple(links)


def _readme_links(
    repository_url: str, readme: str, *, readme_url: str | None, known_urls: Collection[str]
) -> list[RepositoryLink]:
    known_keys = {web_url_key(url) for url in known_urls}
    found: list[RepositoryLink] = []
    for candidate in _extract_candidates(readme):
        url = _resolve_url(candidate.destination, repository_url=repository_url, readme_url=readme_url)
        if url is None or (key := web_url_key(url)) in known_keys:
            continue
        label = _clean_label(candidate.label, url)
        found.append(
            RepositoryLink(id=f"readme-{len(found) + 1}", label=label, url=url, kind=_classify_link(url, label))
        )
        known_keys.add(key)
        if len(found) == _MAX_README_LINKS:
            break
    return found


def _classify_link(url: str, label: str) -> RepositoryLinkKind:
    parsed = urlsplit(url)
    hostname = (parsed.hostname or "").casefold()
    path = parsed.path.casefold()
    parts = path.strip("/").split("/")
    terms = set(re.findall(r"[a-z0-9]+", label.casefold()))

    if hostname == "play.google.com" and path == "/store/apps/details":
        kind = RepositoryLinkKind.APP_STORE
    elif (hostname == "f-droid.org" and path.startswith("/packages/")) or (
        hostname == "apt.izzysoft.de" and path.startswith("/fdroid/index/apk/")
    ):
        kind = RepositoryLinkKind.PACKAGE_REPOSITORY
    elif (release_path := _RELEASE_PATHS.get(hostname)) and release_path.match(path):
        kind = RepositoryLinkKind.RELEASE
    elif hostname in {"github.com", "gitlab.com"} and path.endswith("/issues"):
        kind = RepositoryLinkKind.SUPPORT
    elif hostname in {"ko-fi.com", "opencollective.com", "www.buymeacoffee.com"} or terms & _DONATION_TERMS:
        kind = RepositoryLinkKind.DONATION
    elif terms & _DOCUMENTATION_TERMS or _DOCUMENTATION_TERMS.intersection(parts):
        kind = RepositoryLinkKind.DOCUMENTATION
    elif terms & _SUPPORT_TERMS:
        kind = RepositoryLinkKind.SUPPORT
    else:
        kind = RepositoryLinkKind.OTHER
    return kind


def _resolve_url(destination: str, *, repository_url: str, readme_url: str | None) -> str | None:
    destination = destination.strip()
    if not destination or not destination.isprintable():
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
    label = _WHITESPACE.sub(" ", label.strip(" *_~`|"))
    if not label or label.casefold().startswith(("http://", "https://")):
        parsed = urlsplit(url)
        path_name = unquote(parsed.path).rstrip("/").rsplit("/", 1)[-1]
        label = f"{parsed.netloc}/{path_name}" if path_name else parsed.netloc
    return f"{label[: _MAX_LABEL_LENGTH - 3].rstrip()}..." if len(label) > _MAX_LABEL_LENGTH else label


def _trim_bare_url(url: str) -> str:
    url = url.rstrip(".,;:!?")
    for opening, closing in (("(", ")"), ("[", "]"), ("{", "}")):
        while url.endswith(closing) and url.count(closing) > url.count(opening):
            url = url[:-1]
    return url
