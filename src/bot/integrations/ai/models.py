# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Final

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field  # noqa: TC002

if TYPE_CHECKING:
    from bot.integrations.repositories.models import RepositoryInfo


class RepositoryTag(StrEnum):
    __slots__ = ()

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


@dataclass(slots=True)
class SummaryDependencies:
    repository: RepositoryInfo
    readme_excerpt: str
    links: list[str]
    available_tags: tuple[str, ...]
    reuse_tags: tuple[str, ...] | None = None


@dataclass(slots=True)
class RevisionDependencies:
    repository: RepositoryInfo
    current_summary: RepositorySummary


@dataclass(slots=True)
class SummaryResult:
    summary: RepositorySummary
    model_name: str


@dataclass(slots=True)
class RevisionResult:
    summary: RepositorySummary
    model_name: str


class ImportantLink(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    label: str = Field(
        min_length=1,
        max_length=120,
        description="Descriptive name (e.g., 'Download (Latest Release)', 'F-Droid', 'Google Play')",
    )
    url: AnyHttpUrl = Field(description="The full URL")


class RepositorySummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tags: list[RepositoryTag] = Field(
        min_length=2, max_length=4, description="Select 2-4 tags from the allowed list that best describe the project"
    )
    project_name: str = Field(
        min_length=1, description="The project's display name, extracted from README or documentation"
    )
    enhanced_description: str = Field(
        min_length=1, max_length=280, description="2-3 sentences highlighting user benefits and target audience"
    )
    key_features: list[str] = Field(
        default_factory=list, max_length=4, description="3-4 concise, user-centric features"
    )
    important_links: list[ImportantLink] = Field(
        default_factory=list,
        description="Relevant external links (downloads, stores, docs). Exclude the main repository/README URL.",
    )


class RejectedRepository(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    reason: str = Field(
        min_length=1,
        max_length=200,
        description="Brief explanation of why the repository was rejected (not Android-related)",
    )


ALLOWED_SUMMARY_TAGS: Final[tuple[str, ...]] = tuple(tag.value for tag in RepositoryTag)
