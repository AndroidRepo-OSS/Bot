import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Final, assert_never
from urllib.parse import urlsplit

REPOSITORY_LINK_ID: Final = "repository"


def require_web_url(url: str, *, subject: str = "value") -> str:
    candidate = url.strip()
    try:
        parsed = urlsplit(candidate)
        port = parsed.port
    except ValueError as error:
        msg = f"{subject} must be a valid HTTP or HTTPS URL"
        raise ValueError(msg) from error

    if (
        parsed.scheme.casefold() not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or port == 0
    ):
        msg = f"{subject} must use an HTTP or HTTPS URL"
        raise ValueError(msg)
    return candidate


class RepositoryProvider(StrEnum):
    GITHUB = "github"
    GITLAB = "gitlab"

    @property
    def display_name(self) -> str:
        match self:
            case RepositoryProvider.GITHUB:
                return "GitHub"
            case RepositoryProvider.GITLAB:
                return "GitLab"
            case _:
                assert_never(self)

    @property
    def host(self) -> str:
        match self:
            case RepositoryProvider.GITHUB:
                return "github.com"
            case RepositoryProvider.GITLAB:
                return "gitlab.com"
            case _:
                assert_never(self)

    @classmethod
    def from_host(cls, host: str) -> RepositoryProvider | None:
        match host.casefold():
            case "github.com":
                return cls.GITHUB
            case "gitlab.com":
                return cls.GITLAB
            case _:
                return None


@dataclass(frozen=True, slots=True)
class RepositoryRef:
    provider: RepositoryProvider
    namespace: str
    name: str

    def __post_init__(self) -> None:
        namespace = self.namespace.strip().strip("/")
        name = self.name.strip().removesuffix(".git")
        parts = namespace.split("/")
        if (
            not namespace
            or not name
            or any(not re.fullmatch(r"[A-Za-z0-9_.-]+", part) for part in (*parts, name))
            or (self.provider is RepositoryProvider.GITHUB and len(parts) != 1)
        ):
            msg = f"Invalid {self.provider.display_name} repository reference"
            raise ValueError(msg)
        object.__setattr__(self, "namespace", namespace)
        object.__setattr__(self, "name", name)

    @property
    def full_name(self) -> str:
        return f"{self.namespace}/{self.name}"

    @property
    def url(self) -> str:
        return f"https://{self.provider.host}/{self.full_name}"

    def __str__(self) -> str:
        return self.url


@dataclass(frozen=True, slots=True)
class RepositoryRelease:
    name: str
    tag: str
    url: str
    description: str | None = None

    def __post_init__(self) -> None:
        name = self.name.strip()
        tag = self.tag.strip()
        if not name or not tag:
            msg = "Repository release name and tag must not be empty"
            raise ValueError(msg)
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "tag", tag)
        object.__setattr__(self, "url", require_web_url(self.url, subject="Repository release URL"))


@dataclass(frozen=True, slots=True)
class RepositoryLink:
    id: str
    label: str
    url: str

    def __post_init__(self) -> None:
        link_id = self.id.strip()
        label = self.label.strip()
        if not re.fullmatch(r"[a-z][a-z0-9_-]*", link_id) or not label:
            msg = "Repository link ID must be a lowercase identifier and label must not be empty"
            raise ValueError(msg)
        object.__setattr__(self, "id", link_id)
        object.__setattr__(self, "label", label)
        object.__setattr__(self, "url", require_web_url(self.url, subject="Repository link URL"))


@dataclass(frozen=True, slots=True)
class RepositoryDetails:
    ref: RepositoryRef
    provider_repository_id: str
    display_name: str
    description: str | None
    readme: str | None
    languages: tuple[str, ...]
    license: str | None
    topics: tuple[str, ...]
    homepage: str | None
    release: RepositoryRelease | None
    links: tuple[RepositoryLink, ...]

    def __post_init__(self) -> None:
        provider_repository_id = self.provider_repository_id.strip()
        if not provider_repository_id:
            msg = "Repository provider ID must not be empty"
            raise ValueError(msg)
        display_name = self.display_name.strip()
        if not display_name:
            msg = "Repository display name must not be empty"
            raise ValueError(msg)
        languages = _normalized_unique(self.languages, subject="Repository languages")
        topics = _normalized_unique(self.topics, subject="Repository topics")
        links = tuple(self.links)
        links_by_id = {link.id: link for link in links}
        if REPOSITORY_LINK_ID not in links_by_id:
            msg = "Repository details must include the repository link"
            raise ValueError(msg)
        if len(links_by_id) != len(links):
            msg = "Repository link IDs must be unique"
            raise ValueError(msg)
        if len({link.url for link in links}) != len(links):
            msg = "Repository link URLs must be unique"
            raise ValueError(msg)

        object.__setattr__(self, "provider_repository_id", provider_repository_id)
        object.__setattr__(self, "display_name", display_name)
        object.__setattr__(self, "description", _optional_text(self.description))
        object.__setattr__(self, "readme", _optional_content(self.readme))
        object.__setattr__(self, "languages", languages)
        object.__setattr__(self, "license", _optional_text(self.license))
        object.__setattr__(self, "topics", topics)
        homepage = _optional_text(self.homepage)
        object.__setattr__(
            self, "homepage", require_web_url(homepage, subject="Repository homepage") if homepage else None
        )
        object.__setattr__(self, "links", links)

    @property
    def selectable_link_ids(self) -> frozenset[str]:
        return frozenset(link.id for link in self.links if link.id != REPOSITORY_LINK_ID)

    def link_by_id(self, link_id: str) -> RepositoryLink | None:
        return next((link for link in self.links if link.id == link_id), None)


def _normalized_unique(values: tuple[str, ...], *, subject: str) -> tuple[str, ...]:
    normalized = tuple(value.strip() for value in values)
    if any(not value for value in normalized):
        msg = f"{subject} must not contain empty values"
        raise ValueError(msg)
    if len({value.casefold() for value in normalized}) != len(normalized):
        msg = f"{subject} must contain unique values"
        raise ValueError(msg)
    return normalized


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip() or None


def _optional_content(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    return value
