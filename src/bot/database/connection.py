# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .models import Base


class Database:
    def __init__(self, database_path: str | Path = "data/database.db") -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.last_vacuum: datetime | None = None

        database_url = f"sqlite+aiosqlite:///{self.database_path}"
        self.engine = create_async_engine(database_url, echo=False)

        @event.listens_for(self.engine.sync_engine, "connect")
        def set_sqlite_pragma(dbapi_connection: Any, connection_record: Any) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA cache_size=-2000")
            cursor.execute("PRAGMA temp_store=memory")
            cursor.execute("PRAGMA auto_vacuum=INCREMENTAL")
            cursor.close()

        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)

    async def create_tables(self) -> None:
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def get_session(self) -> AsyncGenerator[AsyncSession]:
        async with self.session_factory() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise

    async def vacuum_if_needed(self) -> None:
        now = datetime.now(UTC)
        if self.last_vacuum and now - self.last_vacuum < timedelta(days=7):
            return

        async with self.engine.connect() as conn:
            result = await conn.execute(text("PRAGMA freelist_count"))
            freelist_count: int | None = result.scalar()

            if freelist_count and freelist_count > 1000:
                await conn.execute(text("VACUUM"))
                self.last_vacuum = now

    async def checkpoint_wal(self) -> None:
        async with self.engine.connect() as conn:
            await conn.execute(text("PRAGMA wal_checkpoint(TRUNCATE)"))

    async def close(self) -> None:
        await self.engine.dispose()


database = Database()
