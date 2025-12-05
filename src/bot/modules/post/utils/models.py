# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations

import base64
from contextlib import suppress
from enum import StrEnum

from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.state import State, StatesGroup
from pydantic import BaseModel, ConfigDict, Field

from bot.integrations.ai import RepositorySummary


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

    model_config = ConfigDict(frozen=True, extra="ignore")

    submission_id: str = Field(description="Unique identifier for this submission")
    caption: str = Field(description="HTML caption rendered for the Telegram post")
    banner_b64: str = Field(description="Base64-encoded preview banner image")
    preview_chat_id: int = Field(description="Chat ID where the preview lives")
    preview_message_id: int = Field(description="Message ID of the preview post")
    original_chat_id: int = Field(description="Chat ID of the user's command message")
    original_message_id: int = Field(description="Message ID of the user's command message")

    prompt_chat_id: int | None = Field(default=None, description="Chat ID of the URL prompt message")
    prompt_message_id: int | None = Field(default=None, description="Message ID of the URL prompt message")
    command_chat_id: int | None = Field(default=None, description="Chat ID of the original /post command")
    command_message_id: int | None = Field(default=None, description="Message ID of the original /post command")

    edit_prompt_chat_id: int | None = Field(default=None, description="Chat ID of the edit prompt message")
    edit_prompt_message_id: int | None = Field(default=None, description="Message ID of the edit prompt message")
    edit_request_chat_id: int | None = Field(default=None, description="Chat ID of the edit request message")
    edit_request_message_id: int | None = Field(default=None, description="Message ID of the edit request message")
    edit_status_chat_id: int | None = Field(default=None, description="Chat ID of the edit status message")
    edit_status_message_id: int | None = Field(default=None, description="Message ID of the edit status message")

    summary: dict[str, object] | None = Field(default=None, description="Serialized repository summary payload")
    debug_url: str | None = Field(default=None, description="Deep link for preview debugging")
    summary_model: str | None = Field(default=None, description="Model used for the summary step")
    revision_model: str | None = Field(default=None, description="Model used for the revision step")

    @classmethod
    def from_state(cls, data: dict[str, object]) -> SubmissionData | None:
        with suppress(Exception):
            return cls.model_validate(data)
        return None

    @property
    def banner_bytes(self) -> bytes | None:
        with suppress(ValueError):
            return base64.b64decode(self.banner_b64, validate=True)
        return None

    @property
    def repository_summary(self) -> RepositorySummary | None:
        if self.summary is None:
            return None
        with suppress(Exception):
            return RepositorySummary.model_validate(self.summary)
        return None

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


__all__ = ("PostStates", "SubmissionAction", "SubmissionCallback", "SubmissionData")
