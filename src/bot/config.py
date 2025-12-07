# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations

from pydantic import SecretStr  # noqa: TC002
from pydantic_settings import BaseSettings, SettingsConfigDict


class BotSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file="data/config.env", env_file_encoding="utf-8", env_prefix="BOT_", extra="ignore"
    )

    token: SecretStr
    ghmodels_api_key: SecretStr
    post_channel_id: int
    post_topic_id: int
    logs_topic_id: int
    allowed_chat_id: int
    database_url: str = "sqlite+aiosqlite:///data/bot.sqlite3"
    github_token: SecretStr | None = None
    gitlab_token: SecretStr | None = None

    @property
    def bot_token(self) -> str:
        return self.token.get_secret_value()

    @property
    def resolved_ghmodels_api_key(self) -> str:
        return self.ghmodels_api_key.get_secret_value()

    @property
    def resolved_github_token(self) -> str | None:
        return self.github_token.get_secret_value() if self.github_token else None

    @property
    def resolved_gitlab_token(self) -> str | None:
        return self.gitlab_token.get_secret_value() if self.gitlab_token else None
