from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from androidrepo_bot.errors import ApplicationError
from androidrepo_bot.repositories.models import RepositoryDetails, RepositoryRef, require_web_url

if TYPE_CHECKING:
    from datetime import datetime


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

    def __post_init__(self) -> None:
        label = self.label.strip()
        if not label:
            msg = "Post link label must not be empty"
            raise ValueError(msg)
        object.__setattr__(self, "label", label)
        object.__setattr__(self, "url", require_web_url(self.url, subject="Post link URL"))


@dataclass(frozen=True, slots=True)
class PostDraft:
    title: str
    summary: str
    features: tuple[str, ...]
    links: tuple[PostLink, ...]
    tags: tuple[PostTag, ...]

    def __post_init__(self) -> None:
        title = self.title.strip()
        summary = self.summary.strip()
        features = tuple(feature.strip() for feature in self.features)
        links = tuple(self.links)
        tags = tuple(self.tags)

        if not title:
            msg = "Post title must not be empty"
            raise ValueError(msg)
        if not summary:
            msg = "Post summary must not be empty"
            raise ValueError(msg)

        minimum_features, maximum_features = 3, 5
        if not minimum_features <= len(features) <= maximum_features:
            msg = "A post must contain between 3 and 5 features"
            raise ValueError(msg)
        if any(not feature for feature in features):
            msg = "Post features must not be empty"
            raise ValueError(msg)
        if len({feature.casefold() for feature in features}) != len(features):
            msg = "Post features must be unique"
            raise ValueError(msg)
        if not links:
            msg = "A post must contain at least one verified link"
            raise ValueError(msg)
        if len({link.url for link in links}) != len(links):
            msg = "Post link URLs must be unique"
            raise ValueError(msg)

        minimum_tags, maximum_tags = 1, 3
        if not minimum_tags <= len(tags) <= maximum_tags:
            msg = "A post must contain between 1 and 3 tags"
            raise ValueError(msg)
        if len(set(tags)) != len(tags):
            msg = "Post tags must be unique"
            raise ValueError(msg)

        object.__setattr__(self, "title", title)
        object.__setattr__(self, "summary", summary)
        object.__setattr__(self, "features", features)
        object.__setattr__(self, "links", links)
        object.__setattr__(self, "tags", tags)


@dataclass(frozen=True, slots=True)
class RegisteredRepository:
    id: int
    ref: RepositoryRef
    provider_repository_id: str


@dataclass(frozen=True, slots=True)
class PublicationCooldown:
    allowed: bool
    blocked_until: datetime | None
    last_published_at: datetime | None


@dataclass(frozen=True, slots=True)
class PublicationRecord:
    repository: RegisteredRepository
    title: str
    tags: tuple[str, ...]
    created_by_user_id: int
    channel_id: int
    channel_message_id: int
    published_at: datetime


@dataclass(frozen=True, slots=True)
class PostCreation:
    repository: RepositoryDetails
    registered_repository: RegisteredRepository
    draft: PostDraft


@dataclass(frozen=True, slots=True)
class CooldownBlockedError(ApplicationError):
    cooldown: PublicationCooldown
