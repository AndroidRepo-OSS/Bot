from typing import Annotated, Literal

from aiogram.utils.token import TokenValidationError, validate_token
from pydantic import PositiveInt, SecretStr, StringConstraints, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

type LogLevel = Literal["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"]


class Settings(BaseSettings):
    bot_token: SecretStr
    staff_chat_id: int
    post_topic_id: PositiveInt
    log_topic_id: PositiveInt
    channel_id: int

    log_level: LogLevel = "INFO"

    opencode_zen_api_key: SecretStr
    opencode_zen_model: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)] = "deepseek-v4-flash"

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
            msg = "AR_BOT_TOKEN must be a valid Telegram bot token"
            raise ValueError(msg) from error
        return value

    @field_validator("opencode_zen_api_key")
    @classmethod
    def validate_required_secret(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().strip():
            msg = "Required secret settings must not be empty"
            raise ValueError(msg)
        return value

    @field_validator("staff_chat_id", "channel_id")
    @classmethod
    def validate_chat_id(cls, value: int) -> int:
        if value == 0:
            msg = "Telegram chat IDs must not be zero"
            raise ValueError(msg)
        return value
