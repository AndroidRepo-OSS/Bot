# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .base import Base

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

type AsyncSessionMaker = async_sessionmaker[AsyncSession]


def create_engine(database_url: str) -> AsyncEngine:
    return create_async_engine(database_url, pool_pre_ping=True)


def create_session_maker(engine: AsyncEngine) -> AsyncSessionMaker:
    return async_sessionmaker(engine, expire_on_commit=False)


async def init_models(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def apply_sqlite_pragmas(engine: AsyncEngine) -> None:
    async with engine.connect() as connection:
        autocommit_connection = await connection.execution_options(isolation_level="AUTOCOMMIT")
        await autocommit_connection.exec_driver_sql("PRAGMA journal_mode=WAL;")
        await autocommit_connection.exec_driver_sql("PRAGMA synchronous=NORMAL;")


async def vacuum_and_analyze(engine: AsyncEngine) -> None:
    async with engine.connect() as connection:
        autocommit_connection = await connection.execution_options(isolation_level="AUTOCOMMIT")
        await autocommit_connection.exec_driver_sql("VACUUM")
        await autocommit_connection.exec_driver_sql("ANALYZE")
