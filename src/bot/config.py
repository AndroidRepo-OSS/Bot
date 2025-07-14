# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from pydantic import Field, SecretStr, computed_field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file="data/config.env",
        env_file_encoding="utf-8",
        env_prefix="",
        case_sensitive=False,
        validate_default=True,
        extra="forbid",
        frozen=True,
    )

    bot_token: SecretStr = Field(
        ..., description="Telegram bot token for authentication", min_length=10
    )

    sudoers: list[int] = Field(
        default=[918317361],
        description="List of user IDs with administrative privileges",
        min_length=1,
    )

    channel_id: int = Field(
        default=-1001258691467, description="Telegram channel ID where posts will be sent"
    )

    group_id: int = Field(
        default=-1002372208018,
        description="Telegram group ID where users can submit posts in topics",
    )

    logs_topic_id: int = Field(
        default=4, ge=0, description="Topic ID for logs in the group (0 to disable logs)"
    )

    openai_api_key: SecretStr = Field(
        ..., description="OpenAI API key for content enhancement", min_length=10
    )

    openai_base_url: str = Field(
        default="https://api.openai.com/v1", description="OpenAI API base URL"
    )

    @field_validator("bot_token", mode="before")
    @classmethod
    def validate_bot_token(cls, v: str | SecretStr) -> SecretStr:
        if isinstance(v, str):
            if not v or len(v.split(":")) != 2:
                msg = 'Bot token must be in format "id:token"'
                raise ValueError(msg)
            return SecretStr(v)
        return v

    @field_validator("openai_base_url")
    @classmethod
    def validate_base_url(cls, v: str) -> str:
        if not v.startswith(("http://", "https://")):
            msg = "Base URL must start with http:// or https://"
            raise ValueError(msg)
        return v.rstrip("/")

    @computed_field
    @property
    def bot_id(self) -> str:
        return self.bot_token.get_secret_value().split(":")[0]


settings = Settings()  # type: ignore
