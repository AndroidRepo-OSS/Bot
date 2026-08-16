from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from androidrepo_bot.errors import ApplicationError

if TYPE_CHECKING:
    from datetime import datetime

    from androidrepo_bot.repositories.models import RepositoryRef


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


@dataclass(frozen=True, slots=True)
class RegisteredRepository:
    id: int
    ref: RepositoryRef


@dataclass(frozen=True, slots=True)
class PublicationCooldown:
    allowed: bool
    blocked_until: datetime | None


@dataclass(frozen=True, slots=True)
class PublicationIntent:
    repository: RegisteredRepository
    title: str
    tags: tuple[str, ...]
    actor_user_id: int
    source_chat_id: int
    source_message_id: int
    channel_id: int


@dataclass(frozen=True, slots=True)
class CooldownBlockedError(ApplicationError):
    cooldown: PublicationCooldown
