# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from pydantic import Field, SecretStr, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file="data/config.env",
        env_file_encoding="utf-8",
        env_prefix="",
        case_sensitive=False,
        validate_default=True,
        extra="forbid",
    )

    bot_token: SecretStr = Field(description="Telegram bot token for authentication")

    sudoers: list[int] = Field(
        default=[918317361],
        description="List of user IDs with administrative privileges",
        min_length=1,
    )

    channel_id: int = Field(
        default=-1001258691467, description="Telegram channel ID where posts will be sent"
    )

    group_id: int = Field(
        default=0, description="Telegram group ID where users can submit posts in topics"
    )

    logs_topic_id: int = Field(
        default=0, description="Topic ID for logs in the group (0 to disable logs)"
    )

    openai_api_key: SecretStr = Field(description="OpenAI API key for content enhancement")
    openai_base_url: str = Field(
        default="https://api.openai.com/v1", description="OpenAI API base URL"
    )

    @computed_field
    @property
    def bot_id(self) -> str:
        return self.bot_token.get_secret_value().split(":")[0]


settings = Settings()  # type: ignore
