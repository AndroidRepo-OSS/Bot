# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations

import base64
from contextlib import suppress
from enum import StrEnum
from typing import Annotated

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

    submission_id: Annotated[str, Field(description="Unique identifier for this submission")]
    caption: Annotated[str, Field(description="HTML caption rendered for the Telegram post")]
    banner_b64: Annotated[str, Field(description="Base64-encoded preview banner image")]
    preview_chat_id: Annotated[int, Field(description="Chat ID where the preview lives")]
    preview_message_id: Annotated[int, Field(description="Message ID of the preview post")]
    original_chat_id: Annotated[int, Field(description="Chat ID of the user's command message")]
    original_message_id: Annotated[int, Field(description="Message ID of the user's command message")]

    prompt_chat_id: Annotated[int | None, Field(description="Chat ID of the URL prompt message")] = None
    prompt_message_id: Annotated[int | None, Field(description="Message ID of the URL prompt message")] = None
    command_chat_id: Annotated[int | None, Field(description="Chat ID of the original /post command")] = None
    command_message_id: Annotated[int | None, Field(description="Message ID of the original /post command")] = None

    edit_prompt_chat_id: Annotated[int | None, Field(description="Chat ID of the edit prompt message")] = None
    edit_prompt_message_id: Annotated[int | None, Field(description="Message ID of the edit prompt message")] = None
    edit_request_chat_id: Annotated[int | None, Field(description="Chat ID of the edit request message")] = None
    edit_request_message_id: Annotated[int | None, Field(description="Message ID of the edit request message")] = None
    edit_status_chat_id: Annotated[int | None, Field(description="Chat ID of the edit status message")] = None
    edit_status_message_id: Annotated[int | None, Field(description="Message ID of the edit status message")] = None

    summary: Annotated[dict[str, object] | None, Field(description="Serialized repository summary payload")] = None
    debug_url: Annotated[str | None, Field(description="Deep link for preview debugging")] = None
    summary_model: Annotated[str | None, Field(description="Model used for the summary step")] = None
    revision_model: Annotated[str | None, Field(description="Model used for the revision step")] = None

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
