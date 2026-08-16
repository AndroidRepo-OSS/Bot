from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

_POOL_SIZE = 5
_MAX_OVERFLOW = 10
_POOL_TIMEOUT_SECONDS = 30.0
_POOL_RECYCLE_SECONDS = 1_800
_CONNECT_TIMEOUT_SECONDS = 10.0
_COMMAND_TIMEOUT_SECONDS = 30.0


@asynccontextmanager
async def database_sessions(database_url: str) -> AsyncGenerator[async_sessionmaker[AsyncSession]]:
    _validate_database_url(database_url)
    engine = create_async_engine(
        database_url,
        echo=False,
        hide_parameters=True,
        pool_pre_ping=True,
        pool_size=_POOL_SIZE,
        max_overflow=_MAX_OVERFLOW,
        pool_timeout=_POOL_TIMEOUT_SECONDS,
        pool_recycle=_POOL_RECYCLE_SECONDS,
        connect_args={"timeout": _CONNECT_TIMEOUT_SECONDS, "command_timeout": _COMMAND_TIMEOUT_SECONDS},
    )
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


def _validate_database_url(database_url: str) -> None:
    try:
        url = make_url(database_url)
    except ArgumentError as error:
        msg = "database_url must be a valid SQLAlchemy URL"
        raise ValueError(msg) from error
    if url.get_backend_name() != "postgresql" or url.get_driver_name() != "asyncpg":
        msg = "database_url must use the postgresql+asyncpg driver"
        raise ValueError(msg)
