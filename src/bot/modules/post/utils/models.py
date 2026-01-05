# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations

import base64
from contextlib import suppress
from enum import StrEnum
from typing import Annotated

from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.state import State, StatesGroup
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

from bot.integrations.ai import RepositorySummary
from bot.integrations.repositories import RepositoryPlatform  # noqa: TC001


class SubmissionAction(StrEnum):
    __slots__ = ()

    PUBLISH = "publish"
    EDIT = "edit"
    CANCEL = "cancel"


class PostStates(StatesGroup):
    __slots__ = ()

    waiting_for_url = State()
    waiting_for_confirmation = State()
    waiting_for_edit_instructions = State()


class SubmissionCallback(CallbackData, prefix="post"):
    __slots__ = ()

    action: SubmissionAction
    submission_id: str


class SubmissionData(BaseModel):
    __slots__ = ()

    _banner_bytes_cache: bytes | None = PrivateAttr(default=None)
    _repository_summary_cache: RepositorySummary | None = PrivateAttr(default=None)

    model_config = ConfigDict(frozen=True, extra="ignore")

    submission_id: Annotated[str, Field(min_length=1, description="Unique identifier for this submission")]
    caption: Annotated[str, Field(min_length=1, max_length=4096, description="HTML caption for Telegram post")]
    banner_b64: Annotated[str, Field(min_length=1, description="Base64-encoded preview banner image")]
    preview_chat_id: Annotated[int, Field(description="Chat ID where the preview lives")]
    preview_message_id: Annotated[int, Field(gt=0, description="Message ID of the preview post")]
    original_chat_id: Annotated[int, Field(description="Chat ID of the user's command message")]
    original_message_id: Annotated[int, Field(gt=0, description="Message ID of the user's command message")]

    prompt_chat_id: Annotated[int | None, Field(default=None, description="Chat ID of the URL prompt message")]
    prompt_message_id: Annotated[int | None, Field(default=None, gt=0, description="Message ID of the URL prompt")]
    command_chat_id: Annotated[int | None, Field(default=None, description="Chat ID of the original /post command")]
    command_message_id: Annotated[int | None, Field(default=None, gt=0, description="Message ID of /post command")]

    edit_prompt_chat_id: Annotated[int | None, Field(default=None, description="Chat ID of the edit prompt")]
    edit_prompt_message_id: Annotated[int | None, Field(default=None, gt=0, description="Message ID of edit prompt")]
    edit_request_chat_id: Annotated[int | None, Field(default=None, description="Chat ID of the edit request")]
    edit_request_message_id: Annotated[int | None, Field(default=None, gt=0, description="Message ID of edit request")]
    edit_status_chat_id: Annotated[int | None, Field(default=None, description="Chat ID of the edit status")]
    edit_status_message_id: Annotated[int | None, Field(default=None, gt=0, description="Message ID of edit status")]

    summary: Annotated[dict[str, object] | None, Field(default=None, description="Serialized repository summary")]
    debug_url: Annotated[str | None, Field(default=None, description="Deep link for preview debugging")]
    summary_model: Annotated[str | None, Field(default=None, description="Model used for the summary step")]
    revision_model: Annotated[str | None, Field(default=None, description="Model used for the revision step")]
    repository_platform: Annotated[RepositoryPlatform | None, Field(default=None, description="Repository platform")]
    repository_owner: Annotated[str | None, Field(default=None, min_length=1, description="Repository owner/namespace")]
    repository_name: Annotated[str | None, Field(default=None, min_length=1, description="Repository name")]

    @classmethod
    def from_state(cls, data: dict[str, object]) -> SubmissionData | None:
        with suppress(Exception):
            return cls.model_validate(data)
        return None

    @property
    def banner_bytes(self) -> bytes | None:
        if self._banner_bytes_cache is not None:
            return self._banner_bytes_cache

        with suppress(ValueError):
            decoded = base64.b64decode(self.banner_b64, validate=True)
            self._banner_bytes_cache = decoded
            return decoded
        return None

    @property
    def repository_summary(self) -> RepositorySummary | None:
        if self._repository_summary_cache is not None:
            return self._repository_summary_cache
        if self.summary is None:
            return None
        with suppress(Exception):
            parsed = RepositorySummary.model_validate(self.summary)
            self._repository_summary_cache = parsed
            return parsed
        return None

    @property
    def repository_identity(self) -> tuple[RepositoryPlatform, str, str] | None:
        if not (self.repository_platform and self.repository_owner and self.repository_name):
            return None
        return self.repository_platform, self.repository_owner, self.repository_name

    @property
    def cleanup_targets(self) -> list[tuple[int, int]]:
        pairs = (
            (self.original_chat_id, self.original_message_id),
            (self.prompt_chat_id, self.prompt_message_id),
            (self.command_chat_id, self.command_message_id),
            (self.edit_prompt_chat_id, self.edit_prompt_message_id),
            (self.edit_request_chat_id, self.edit_request_message_id),
            (self.edit_status_chat_id, self.edit_status_message_id),
        )
        return [(chat_id, message_id) for chat_id, message_id in pairs if chat_id and message_id]
