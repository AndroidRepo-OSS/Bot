from dataclasses import dataclass


@dataclass(frozen=True, slots=True, kw_only=True)
class BannerRequest:
    project_name: str
    repository: str
    provider: str
    primary_language: str | None = None
    license_name: str | None = None
    release: str | None = None
    topics: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        project_name = " ".join(self.project_name.split())
        repository = " ".join(self.repository.split())
        provider = " ".join(self.provider.split())
        if not project_name or not repository or not provider:
            msg = "Banner project name, repository, and provider must not be empty"
            raise ValueError(msg)

        object.__setattr__(self, "project_name", project_name)
        object.__setattr__(self, "repository", repository)
        object.__setattr__(self, "provider", provider)
        object.__setattr__(self, "primary_language", _optional_text(self.primary_language))
        object.__setattr__(self, "license_name", _optional_text(self.license_name))
        object.__setattr__(self, "release", _optional_text(self.release))
        object.__setattr__(self, "topics", tuple(filter(None, (" ".join(topic.split()) for topic in self.topics))))


@dataclass(frozen=True, slots=True, kw_only=True)
class SpaceArtwork:
    content: bytes
    identifier: str
    title: str
    center: str
    date_created: str | None
    credit: str

    def __post_init__(self) -> None:
        if not self.content:
            msg = "Space artwork content must not be empty"
            raise ValueError(msg)
        for value, subject in (
            (self.identifier, "identifier"),
            (self.title, "title"),
            (self.center, "center"),
            (self.credit, "credit"),
        ):
            if not value.strip():
                msg = f"Space artwork {subject} must not be empty"
                raise ValueError(msg)


@dataclass(frozen=True, slots=True, kw_only=True)
class BannerImage:
    content: bytes
    filename: str
    artwork_id: str


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    return " ".join(value.split()) or None
