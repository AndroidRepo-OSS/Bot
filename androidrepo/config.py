# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2023 Hitalo M. <https://github.com/HitaloM>

from pydantic import AnyHttpUrl, BaseSettings, SecretStr


class Settings(BaseSettings):
    bot_token: SecretStr
    redis_host: str = "localhost"
    sentry_url: AnyHttpUrl | None
    sudoers: list[int] = [918317361]

    class Config:
        env_file = "data/config.env"
        env_file_encoding = "utf-8"


config = Settings()  # type: ignore[arg-type]
