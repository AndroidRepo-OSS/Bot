from typing import Literal, Self

from aiogram.utils.token import TokenValidationError, validate_token
from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LogLevel = Literal["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"]


class Settings(BaseSettings):
    bot_token: SecretStr
    staff_chat_id: int
    post_topic_id: int
    log_topic_id: int
    channel_id: int

    log_level: LogLevel = "INFO"

    opencode_zen_api_key: SecretStr
    opencode_zen_model: str = "deepseek-v4-flash"

    github_token: SecretStr | None = None
    gitlab_token: SecretStr | None = None
    database_url: SecretStr

    model_config = SettingsConfigDict(
        env_prefix="AR_",
        env_file=".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
        frozen=True,
        hide_input_in_errors=True,
    )

    @field_validator("bot_token")
    @classmethod
    def validate_bot_token(cls, value: SecretStr) -> SecretStr:
        try:
            validate_token(value.get_secret_value())
        except TokenValidationError as error:
            message = "AR_BOT_TOKEN must be a valid Telegram bot token"
            raise ValueError(message) from error
        return value

    @field_validator("opencode_zen_api_key")
    @classmethod
    def validate_required_secret(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().strip():
            message = "Required secret settings must not be empty"
            raise ValueError(message)
        return value

    @field_validator("opencode_zen_model")
    @classmethod
    def validate_opencode_zen_model(cls, value: str) -> str:
        value = value.strip()
        if not value:
            message = "AR_OPENCODE_ZEN_MODEL must not be empty"
            raise ValueError(message)
        return value

    @model_validator(mode="after")
    def validate_telegram_targets(self) -> Self:
        if self.staff_chat_id == 0:
            message = "AR_STAFF_CHAT_ID must not be zero"
            raise ValueError(message)
        if self.post_topic_id <= 0:
            message = "AR_POST_TOPIC_ID must be a positive message thread ID"
            raise ValueError(message)
        if self.log_topic_id <= 0:
            message = "AR_LOG_TOPIC_ID must be a positive message thread ID"
            raise ValueError(message)
        if self.channel_id == 0:
            message = "AR_CHANNEL_ID must not be zero"
            raise ValueError(message)
        return self
