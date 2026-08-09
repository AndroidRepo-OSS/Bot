import re
from enum import StrEnum
from typing import Annotated, Self, cast

from pydantic import AfterValidator, BaseModel, BeforeValidator, ConfigDict, Field, model_validator

from androidrepo_bot.posts.models import PostTag

_URL_PATTERN = re.compile(r"(?:https?://|www\.)", re.IGNORECASE)
_HTML_PATTERN = re.compile(r"</?[a-z][^>]*>", re.IGNORECASE)
_MARKDOWN_PATTERNS = (
    re.compile(r"(?m)^\s{0,3}(?:[-+*]|\d+[.)])\s+"),
    re.compile(r"(?m)^\s{0,3}(?:#{1,6}|>)\s+"),
    re.compile(r"\[[^\]]+]\([^)]+\)"),
    re.compile(r"(?<!\w)(?:\*\*|__|~~|`)[^\n]+?(?:\*\*|__|~~|`)"),
)
_HASHTAG_PATTERN = re.compile(r"(?<!\w)#[\w-]+")
_BULLET_SYMBOL_PATTERN = re.compile(r"[\u2022\u2023\u2043\u25aa\u25ab\u25e6]")
_PICTOGRAPH_PATTERN = re.compile(r"[\u2600-\u27bf\U0001f000-\U0001faff]")


class EvidenceTrust(StrEnum):
    UNTRUSTED = "untrusted_evidence"
    VERIFIED_DESTINATIONS = "verified_destinations_with_untrusted_labels"


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class RepositoryOverview(_StrictModel):
    api_display_name: str
    repository_slug: str
    repository: str
    provider: str
    description: str | None
    languages: tuple[str, ...]
    license: str | None
    topics: tuple[str, ...]
    homepage: str | None
    has_readme: bool
    has_release: bool


class RepositoryOverviewEvidence(_StrictModel):
    source: str = "repository_metadata"
    trust: EvidenceTrust = EvidenceTrust.UNTRUSTED
    data: RepositoryOverview


class RepositoryReadmeEvidence(_StrictModel):
    source: str = "repository_readme"
    trust: EvidenceTrust = EvidenceTrust.UNTRUSTED
    available: bool
    truncated: bool
    characters_returned: int
    data: str | None


class LatestRelease(_StrictModel):
    name: str
    tag: str
    description: str | None


class LatestReleaseEvidence(_StrictModel):
    source: str = "latest_release"
    trust: EvidenceTrust = EvidenceTrust.UNTRUSTED
    data: LatestRelease


class RepositoryLinkEvidence(_StrictModel):
    id: str
    label: str
    url: str


class RepositoryLinks(_StrictModel):
    repository: RepositoryLinkEvidence
    selectable: tuple[RepositoryLinkEvidence, ...]


class RepositoryLinksEvidence(_StrictModel):
    source: str = "verified_repository_links"
    trust: EvidenceTrust = EvidenceTrust.VERIFIED_DESTINATIONS
    data: RepositoryLinks


class RepositoryEvidence(_StrictModel):
    overview: RepositoryOverviewEvidence
    readme: RepositoryReadmeEvidence
    latest_release: LatestReleaseEvidence | None
    links: RepositoryLinksEvidence


def _normalize_text(value: object) -> object:
    return " ".join(value.split()) if isinstance(value, str) else value


def _json_array_to_tuple(value: object) -> object:
    return tuple(cast("list[object]", value)) if isinstance(value, list) else value


def _normalize_tags(value: object) -> object:
    values = _json_array_to_tuple(value)
    if not isinstance(values, tuple):
        return values

    items = cast("tuple[object, ...]", values)
    try:
        return tuple(PostTag(item) if isinstance(item, str) else item for item in items)
    except ValueError:
        return items


def _normalize_project_name(value: object) -> object:
    if not isinstance(value, str):
        return value
    if any(character in value for character in "\r\n\t"):
        msg = "Project name must be a single line"
        raise ValueError(msg)
    return " ".join(value.split())


def _validate_plain_text(value: str) -> str:
    if _URL_PATTERN.search(value):
        msg = "Generated text fields must not contain URLs"
        raise ValueError(msg)
    if _HTML_PATTERN.search(value):
        msg = "Generated text fields must not contain HTML"
        raise ValueError(msg)
    if any(pattern.search(value) for pattern in _MARKDOWN_PATTERNS):
        msg = "Generated text fields must not contain Markdown formatting"
        raise ValueError(msg)
    if _HASHTAG_PATTERN.search(value):
        msg = "Generated text fields must not contain hashtags"
        raise ValueError(msg)
    if _BULLET_SYMBOL_PATTERN.search(value):
        msg = "Generated text fields must not contain bullet symbols"
        raise ValueError(msg)
    if _PICTOGRAPH_PATTERN.search(value):
        msg = "Generated text fields must not contain emojis or pictographic symbols"
        raise ValueError(msg)

    return value


ProjectName = Annotated[
    str,
    BeforeValidator(_normalize_project_name),
    Field(
        min_length=1,
        max_length=100,
        description=(
            "The canonical public-facing project name supported by repository "
            "metadata or README branding, not a repository slug or owner/name."
        ),
    ),
    AfterValidator(_validate_plain_text),
]
Summary = Annotated[
    str,
    BeforeValidator(_normalize_text),
    Field(
        min_length=1,
        max_length=280,
        description=(
            "One concise factual paragraph describing the project's purpose "
            "and primary use case. Return a complete thought of at most 280 "
            "characters; do not truncate it, list features, or repeat the title."
        ),
    ),
    AfterValidator(_validate_plain_text),
]
Feature = Annotated[
    str,
    BeforeValidator(_normalize_text),
    Field(
        min_length=1,
        max_length=90,
        description=(
            "One source-supported user-facing capability that adds information "
            "not stated in the summary or any other feature. Return a complete "
            "phrase of at most 90 characters; never truncate it."
        ),
    ),
    AfterValidator(_validate_plain_text),
]
LinkId = Annotated[
    str,
    BeforeValidator(_normalize_text),
    Field(min_length=1, max_length=40, description="An exact selectable link ID."),
]
LinkLabel = Annotated[
    str,
    BeforeValidator(_normalize_text),
    Field(
        min_length=1,
        max_length=60,
        description=(
            "Plain-text canonical public name of the selected destination or "
            "service, derived from its verified URL; never badge or action text."
        ),
    ),
    AfterValidator(_validate_plain_text),
]


class GeneratedLink(_StrictModel):
    id: LinkId
    label: LinkLabel


class NotAndroidProject(_StrictModel):
    reason: Annotated[
        str,
        BeforeValidator(_normalize_text),
        Field(min_length=1, max_length=280, description="Evidence-based reason the project is not related to Android."),
        AfterValidator(_validate_plain_text),
    ]


class MissingDownloadSource(_StrictModel):
    reason: Annotated[
        str,
        BeforeValidator(_normalize_text),
        Field(
            min_length=1,
            max_length=280,
            description="Evidence-based explanation that no official install or release download source was found.",
        ),
        AfterValidator(_validate_plain_text),
    ]


class GeneratedPost(_StrictModel):
    project_name: ProjectName
    summary: Summary
    features: Annotated[
        tuple[Feature, ...],
        BeforeValidator(_json_array_to_tuple),
        Field(
            min_length=3,
            max_length=5,
            description=(
                "Distinct evidence-supported technical or user-facing capabilities, "
                "ordered by reader value and not overlapping with the summary."
            ),
        ),
    ]
    links: Annotated[
        tuple[GeneratedLink, ...],
        BeforeValidator(_json_array_to_tuple),
        Field(max_length=4, description="Useful non-repository destinations selected only by exact inspected link ID."),
    ] = ()
    download_link_id: LinkId | None = Field(
        description=(
            "The exact ID of the most appropriate official install or release download destination in the supplied "
            "selectable links, or null only when the user explicitly approved generation without one."
        )
    )
    tags: Annotated[
        tuple[PostTag, ...],
        BeforeValidator(_normalize_tags),
        Field(
            min_length=1,
            max_length=3,
            description=(
                "One to three distinct categories that best describe the project, "
                "selected only from the supported enum."
            ),
        ),
    ]

    @model_validator(mode="after")
    def validate_distinct_values(self) -> Self:
        normalized_features = {feature.casefold() for feature in self.features}
        if len(normalized_features) != len(self.features):
            msg = "Key features must be distinct"
            raise ValueError(msg)

        link_ids = [link.id for link in self.links]
        if len(set(link_ids)) != len(link_ids):
            msg = "Link IDs must not be repeated"
            raise ValueError(msg)

        if len(set(self.tags)) != len(self.tags):
            msg = "Tags must not be repeated"
            raise ValueError(msg)

        return self


type GeneratedOutput = GeneratedPost | NotAndroidProject | MissingDownloadSource
