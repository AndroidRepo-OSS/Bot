from dataclasses import dataclass

_MAX_PROJECT_NAME_LENGTH = 200
_MAX_REPOSITORY_LENGTH = 300
_MAX_PROVIDER_LENGTH = 50
_MAX_METADATA_LENGTH = 200
_MAX_TOPIC_LENGTH = 100
_MAX_TOPICS = 20


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
        object.__setattr__(
            self,
            "project_name",
            _required_text(self.project_name, subject="project name", max_length=_MAX_PROJECT_NAME_LENGTH),
        )
        object.__setattr__(
            self, "repository", _required_text(self.repository, subject="repository", max_length=_MAX_REPOSITORY_LENGTH)
        )
        object.__setattr__(
            self, "provider", _required_text(self.provider, subject="provider", max_length=_MAX_PROVIDER_LENGTH)
        )
        object.__setattr__(
            self,
            "primary_language",
            _optional_text(self.primary_language, subject="primary language", max_length=_MAX_METADATA_LENGTH),
        )
        object.__setattr__(
            self, "license_name", _optional_text(self.license_name, subject="license", max_length=_MAX_METADATA_LENGTH)
        )
        object.__setattr__(
            self, "release", _optional_text(self.release, subject="release", max_length=_MAX_METADATA_LENGTH)
        )
        if len(self.topics) > _MAX_TOPICS:
            msg = f"Banner topics must contain at most {_MAX_TOPICS} values"
            raise ValueError(msg)
        topics = tuple(
            normalized
            for topic in self.topics
            if (normalized := _optional_text(topic, subject="topic", max_length=_MAX_TOPIC_LENGTH)) is not None
        )
        object.__setattr__(self, "topics", topics)


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
        for field_name, value, subject, max_length in (
            ("identifier", self.identifier, "identifier", 200),
            ("title", self.title, "title", 500),
            ("center", self.center, "center", 200),
            ("credit", self.credit, "credit", 300),
        ):
            object.__setattr__(
                self, field_name, _required_text(value, subject=f"artwork {subject}", max_length=max_length)
            )
        object.__setattr__(
            self, "date_created", _optional_text(self.date_created, subject="artwork creation date", max_length=100)
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class BannerImage:
    content: bytes
    filename: str
    artwork_id: str

    def __post_init__(self) -> None:
        if not self.content:
            msg = "Banner image content must not be empty"
            raise ValueError(msg)
        object.__setattr__(self, "filename", _required_text(self.filename, subject="banner filename", max_length=255))
        object.__setattr__(
            self, "artwork_id", _required_text(self.artwork_id, subject="banner artwork identifier", max_length=200)
        )


def _required_text(value: str, *, subject: str, max_length: int) -> str:
    normalized = " ".join(value.split())
    if not normalized:
        msg = f"{subject.capitalize()} must not be empty"
        raise ValueError(msg)
    if len(normalized) > max_length:
        msg = f"{subject.capitalize()} exceeds {max_length} characters"
        raise ValueError(msg)
    return normalized


def _optional_text(value: str | None, *, subject: str, max_length: int) -> str | None:
    if value is None:
        return None
    normalized = " ".join(value.split())
    if not normalized:
        return None
    if len(normalized) > max_length:
        msg = f"{subject.capitalize()} exceeds {max_length} characters"
        raise ValueError(msg)
    return normalized
