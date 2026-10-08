import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated, Self

from pydantic import AfterValidator, BaseModel, BeforeValidator, ConfigDict, Field, model_validator


class PostTag(StrEnum):
    TWO_FA = "2FA"
    AI_CHAT = "AI_Chat"
    APP_STORE = "App_Store"
    AUTOMATION = "Automation"
    BOOKMARK = "Bookmark"
    BROWSER = "Browser"
    CALCULATOR = "Calculator"
    CALENDAR = "Calendar"
    CLOUD_STORAGE = "Cloud_Storage"
    CONNECTIVITY = "Connectivity"
    DEVELOPMENT = "Development"
    DICTIONARY = "Dictionary"
    DNS = "DNS"
    DRAW = "Draw"
    EBOOK_READER = "Ebook_Reader"
    EMAIL = "Email"
    FILE_ENCRYPTION = "File_Encryption"
    FILE_TRANSFER = "File_Transfer"
    FOOD = "Food"
    FORUM = "Forum"
    GALLERY = "Gallery"
    GAMES = "Games"
    GRAPHICS = "Graphics"
    HABIT_TRACKER = "Habit_Tracker"
    HEALTH = "Health"
    ICON_PACK = "Icon_Pack"
    INTERNET = "Internet"
    KEYBOARD = "Keyboard"
    LAUNCHER = "Launcher"
    LOCAL_MEDIA_PLAYER = "Local_Media_Player"
    LOCATION_TRACKER = "Location_Tracker"
    MESSAGING = "Messaging"
    MONEY = "Money"
    MULTIMEDIA = "Multimedia"
    MUSIC_PRACTICE_TOOL = "Music_Practice_Tool"
    NAVIGATION = "Navigation"
    NEWS = "News"
    NOTE = "Note"
    OFFICE = "Office"
    ONLINE_MEDIA_PLAYER = "Online_Media_Player"
    PASSWORD = "Password"
    PHONE = "Phone"
    PODCAST = "Podcast"
    PROXY = "Proxy"
    PUBLIC_TRANSPORT = "Public_Transport"
    READING = "Reading"
    RECIPE_MANAGER = "Recipe_Manager"
    RELIGION = "Religion"
    SCIENCE = "Science"
    SECURITY = "Security"
    SHOPPING_LIST = "Shopping_List"
    SMS = "SMS"
    SOCIAL_NETWORK = "Social_Network"
    SYSTEM = "System"
    TASK = "Task"
    TEXT_EDITOR = "Text_Editor"
    THEMING = "Theming"
    TIME = "Time"
    TRANSLATION = "Translation"
    UNIT_CONVERTOR = "Unit_Convertor"
    UPDATER = "Updater"
    VIDEO_CHAT = "Video_Chat"
    VOICE_CHAT = "Voice_Chat"
    VPN = "VPN"
    WALLET = "Wallet"
    WALLPAPER = "Wallpaper"
    WEATHER = "Weather"
    WORKOUT = "Workout"
    WRITING = "Writing"
    XPOSED = "Xposed"
    SUPER_USER = "Super_User"


@dataclass(frozen=True, slots=True)
class PostLink:
    label: str
    url: str


@dataclass(frozen=True, slots=True)
class PostDraft:
    title: str
    summary: str
    features: tuple[str, ...]
    links: tuple[PostLink, ...]
    download_url: str | None
    tags: tuple[PostTag, ...]


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


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


def _normalize_text(value: object) -> object:
    return " ".join(value.split()) if isinstance(value, str) else value


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
GeneratedTag = Annotated[PostTag, Field(strict=False)]


class GeneratedLink(_StrictModel):
    id: LinkId
    label: LinkLabel


Reason = Annotated[
    str, BeforeValidator(_normalize_text), Field(min_length=1, max_length=280), AfterValidator(_validate_plain_text)
]


class NotAndroidProject(_StrictModel):
    reason: Annotated[
        Reason,
        Field(description="Evidence-based reason the project is affirmatively outside the Android project scope."),
    ]


class InsufficientRepositoryEvidence(_StrictModel):
    reason: Annotated[Reason, Field(description="Specific evidence gap that prevents a complete grounded post draft.")]


class MissingDownloadSource(_StrictModel):
    reason: Annotated[
        Reason,
        Field(description="Evidence-based explanation that no official install or release download source was found."),
    ]


class GeneratedPost(_StrictModel):
    project_name: ProjectName
    summary: Summary
    features: Annotated[
        tuple[Feature, ...],
        Field(
            strict=False,
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
        Field(
            strict=False,
            max_length=4,
            description="Useful non-repository destinations selected only by exact inspected link ID.",
        ),
    ] = ()
    download_link_id: LinkId | None = Field(
        description=(
            "The exact ID of the most appropriate official install or release download destination in the supplied "
            "selectable links, or null only when the user explicitly approved generation without one."
        )
    )
    tags: Annotated[
        tuple[GeneratedTag, ...],
        Field(
            strict=False,
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


type GeneratedOutput = GeneratedPost | NotAndroidProject | InsufficientRepositoryEvidence | MissingDownloadSource
