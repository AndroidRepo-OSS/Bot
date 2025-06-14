# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from pydantic import Field, SecretStr, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables and .env files.

    This class follows Pydantic Settings best practices including:
    - Using SettingsConfigDict for configuration
    - Proper field descriptions and validation
    - Secret handling for sensitive data
    - Environment variable validation
    """

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

    @computed_field
    @property
    def bot_id(self) -> str:
        """
        Retrieve the bot ID derived from the bot token.

        Returns:
            str: The bot ID, which is the first component of the bot token.
        """
        return self.bot_token.get_secret_value().split(":")[0]
