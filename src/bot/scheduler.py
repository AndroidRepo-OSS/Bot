# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

import base64
import logging
from datetime import UTC, datetime, timedelta
from io import BytesIO
from types import TracebackType
from typing import Self

from aiogram import Bot
from aiogram.types import BufferedInputFile
from apscheduler import AsyncScheduler
from apscheduler.datastores.sqlalchemy import SQLAlchemyDataStore
from apscheduler.eventbrokers.local import LocalEventBroker
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from bot.config import Settings
from bot.database import (
    cleanup_orphaned_posts,
    database,
    get_last_submission_time,
    get_next_slot,
    mark_post_published,
    update_post_time,
)
from bot.database.models import ScheduledPost

logger = logging.getLogger(__name__)


def to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


class PostScheduler:
    def __init__(self, bot: Bot, settings: Settings) -> None:
        self.bot = bot
        self.settings = settings

        data_store = SQLAlchemyDataStore(
            "sqlite:///data/scheduler_jobs.db", start_from_scratch=False
        )
        event_broker = LocalEventBroker()
        self.scheduler = AsyncScheduler(data_store, event_broker)
        self._started: bool = False

    async def __aenter__(self) -> Self:
        await self.scheduler.__aenter__()
        if not self._started:
            await self.scheduler.add_schedule(
                self._cleanup_orphaned, IntervalTrigger(hours=24), id="cleanup_old_posts"
            )
            await self.scheduler.add_schedule(
                self._database_maintenance, IntervalTrigger(days=7), id="database_maintenance"
            )
            logger.info("Post scheduler started")
        self._started = True
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        if self._started:
            await self.scheduler.__aexit__(exc_type, exc_val, exc_tb)
            self._started = False
            logger.info("Post scheduler stopped")

    @staticmethod
    async def _cleanup_orphaned() -> None:
        try:
            orphaned_count = await cleanup_orphaned_posts(days_old=3)

            if orphaned_count > 0:
                logger.info("Daily cleanup: %d orphaned scheduled posts", orphaned_count)

        except Exception as e:
            logger.error("Failed to cleanup old posts: %s", e)

    @staticmethod
    async def _database_maintenance() -> None:
        try:
            await database.vacuum_if_needed()
            await database.checkpoint_wal()
            logger.info("Database maintenance completed")
        except Exception as e:
            logger.error("Failed to perform database maintenance: %s", e)

    @staticmethod
    def round_to_interval(
        slot: datetime,
        interval_minutes: int = 15,
    ) -> datetime:
        slot = to_utc(slot)

        minute = (slot.minute // interval_minutes) * interval_minutes
        if slot.minute % interval_minutes:
            minute += interval_minutes
        if minute >= 60:
            slot = slot.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        else:
            slot = slot.replace(minute=minute, second=0, microsecond=0)
        return slot

    async def schedule_post(
        self,
        post: ScheduledPost,
        post_text: str,
        banner_buffer: BytesIO,
        banner_filename: str,
    ) -> None:
        if not post or not post.id:
            msg = "Invalid post provided for scheduling"
            raise ValueError(msg)

        if not post_text.strip():
            msg = "Post text cannot be empty"
            raise ValueError(msg)

        if not banner_filename:
            msg = "Banner filename cannot be empty"
            raise ValueError(msg)

        job_id = f"post_{post.id}_{post.repository_id}"
        scheduled_time = to_utc(post.scheduled_time)

        last_post_time = await get_last_submission_time()
        if last_post_time:
            time_diff_hours = (scheduled_time - last_post_time).total_seconds() / 3600
            if time_diff_hours < 1.0:
                scheduled_time = last_post_time + timedelta(hours=1)
                logger.info(
                    "Adjusted scheduled time for post %d to maintain 1-hour interval. "
                    "New time: %s",
                    post.id,
                    scheduled_time,
                )

        run_date = self.round_to_interval(scheduled_time)

        if run_date != scheduled_time:
            await update_post_time(post.id, run_date)

        try:
            banner_data = banner_buffer.getvalue()
            if not isinstance(banner_data, bytes):
                banner_data = bytes(banner_data)

            banner_b64 = base64.b64encode(banner_data).decode("utf-8")

            await self.scheduler.add_schedule(
                publish_post,
                DateTrigger(run_date),
                args=[
                    int(post.id),
                    str(post_text),
                    banner_b64,
                    str(banner_filename),
                    str(self.settings.channel_id),
                    str(self.bot.token),
                ],
                id=job_id,
                metadata={"job_id": job_id, "scheduled_time": str(run_date)},
            )
            logger.info(
                "Scheduled post for %s at %s (Job ID: %s)",
                post.repository_full_name,
                run_date,
                job_id,
            )
        except Exception as e:
            logger.exception("Failed to schedule post %d: %s", post.id, e)
            msg = f"Failed to schedule post {post.id}: {e!s}"
            raise RuntimeError(msg) from e

    @staticmethod
    async def get_next_slot(base_time: datetime | None = None) -> datetime:
        return await get_next_slot(base_time)


async def publish_post(
    post_id: int,
    post_text: str,
    banner_b64: str,
    banner_filename: str,
    channel_id: str,
    bot_token: str,
) -> None:
    logger = logging.getLogger(__name__)

    try:
        bot = Bot(token=bot_token)

        banner_data = base64.b64decode(banner_b64)
        banner_input = BufferedInputFile(banner_data, filename=banner_filename)

        sent_message = await bot.send_photo(
            chat_id=int(channel_id),
            photo=banner_input,
            caption=post_text,
        )

        try:
            await mark_post_published(post_id, sent_message.message_id)
            logger.info("Successfully published scheduled post %s", post_id)
        except Exception as db_error:
            logger.error(
                "Published post %s to channel but failed to update database: %s",
                post_id,
                db_error,
            )
            logger.info("Post was sent with message_id: %s", sent_message.message_id)
            raise
        finally:
            await bot.session.close()

    except Exception as e:
        logger.error("Failed to publish scheduled post %s: %s", post_id, e)
        raise
