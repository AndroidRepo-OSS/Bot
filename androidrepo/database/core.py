# SPDX-License-Identifier: GPL-3.0
# Copyright (c) 2021-2022 Amano Team

import logging

import aiosqlite

from androidrepo.config import DATABASE_PATH

logger = logging.getLogger(__name__)


class Database(object):
    def __init__(self):
        self.conn: aiosqlite.Connection = None
        self.path: str = DATABASE_PATH
        self.is_connected: bool = False

    async def connect(self):
        # Open the connection
        conn = await aiosqlite.connect(self.path)

        # Define the tables
        await conn.executescript(
            """
        CREATE TABLE IF NOT EXISTS contact (
                id INTEGER PRIMARY KEY,
                user INTEGER
        );
        CREATE TABLE IF NOT EXISTS modules (
                id TEXT PRIMARY KEY,
                url TEXT,
                name TEXT,
                version TEXT,
                version_code INTENGER,
                last_update INTEGER
        );
        CREATE TABLE IF NOT EXISTS magisk (
                branch TEXT PRIMARY KEY,
                version TEXT,
                version_code INTEGER,
                link TEXT,
                note TEXT,
                changelog TEXT
        );
        CREATE TABLE IF NOT EXISTS requests (
                id INTEGER PRIMARY KEY,
                user INTEGER,
                time INTEGER,
                ignore INTEGER,
                request TEXT,
                attempts INTEGER,
                request_id INTEGER,
                message_id INTEGER
        );
        CREATE TABLE IF NOT EXISTS lsposed (
                branch TEXT PRIMARY KEY,
                version TEXT,
                version_code INTEGER,
                link TEXT,
                changelog TEXT
        );
        CREATE TABLE IF NOT EXISTS quickpic (
                branch TEXT PRIMARY KEY,
                version INTENGER,
                download_url TEXT,
                changelog TEXT
        );
        """
        )

        # Enable VACUUM
        await conn.execute("VACUUM")

        # Enable WAL
        await conn.execute("PRAGMA journal_mode=WAL")

        # Update the database
        await conn.commit()

        conn.row_factory = aiosqlite.Row

        self.conn = conn
        self.is_connected: bool = True

        logger.info("The database has been connected.")

    async def close(self):
        # Close the connection
        await self.conn.close()

        self.is_connected: bool = False

        logger.info("The database was closed.")

    def get_conn(self) -> aiosqlite.Connection:
        if not self.is_connected:
            raise RuntimeError("The database is not connected.")

        return self.conn


database = Database()
