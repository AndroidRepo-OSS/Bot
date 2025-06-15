# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations

from collections.abc import AsyncGenerator
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .models import Base


class DatabaseConnection:
    def __init__(self, database_path: str | Path = "data/apps.db"):
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)

        self.database_url = f"sqlite+aiosqlite:///{self.database_path}"
        self.engine = create_async_engine(self.database_url, echo=False, future=True)
        self.async_session = async_sessionmaker(
            self.engine, class_=AsyncSession, expire_on_commit=False
        )

    async def create_tables(self) -> None:
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def get_session(self) -> AsyncGenerator[AsyncSession]:
        async with self.async_session() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()

    async def close(self) -> None:
        await self.engine.dispose()

    async def __aenter__(self) -> DatabaseConnection:
        await self.create_tables()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()


class DatabaseManager:
    def __init__(self):
        self._db_connection: DatabaseConnection | None = None

    def get_database(self) -> DatabaseConnection:
        if self._db_connection is None:
            self._db_connection = DatabaseConnection()
        return self._db_connection

    async def init_database(self) -> None:
        db = self.get_database()
        await db.create_tables()

    async def close_database(self) -> None:
        if self._db_connection is not None:
            await self._db_connection.close()
            self._db_connection = None


db_manager = DatabaseManager()
