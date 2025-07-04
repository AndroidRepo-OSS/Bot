# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from aiogram import Bot
from aiogram.types import BufferedInputFile
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from bot.config import Settings
from bot.database import (
    cleanup_orphaned_scheduled_posts,
    get_last_post_time,
    get_next_available_slot_with_lock,
    update_scheduled_post_as_published,
    update_scheduled_post_time,
)
from bot.database.models import ScheduledPost

if TYPE_CHECKING:
    from io import BytesIO

logger = logging.getLogger(__name__)


def ensure_timezone_aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


class PostScheduler:
    def __init__(self, bot: Bot, settings: Settings) -> None:
        self.bot = bot
        self.settings = settings

        jobstore = SQLAlchemyJobStore(url="sqlite:///data/scheduler_jobs.db")
        self.scheduler = AsyncIOScheduler(jobstores={"default": jobstore}, timezone="UTC")

    async def start(self) -> None:
        self.scheduler.start()
        self.scheduler.add_job(
            self._cleanup_old_posts,
            "interval",
            hours=24,
            id="cleanup_old_posts",
            replace_existing=True,
        )
        logger.info("Post scheduler started")

    @staticmethod
    async def _cleanup_old_posts() -> None:
        try:
            orphaned_count = await cleanup_orphaned_scheduled_posts(days_old=3)

            if orphaned_count > 0:
                logger.info("Daily cleanup: %d orphaned scheduled posts", orphaned_count)

        except Exception as e:
            logger.error("Failed to cleanup old posts: %s", e)

    async def stop(self) -> None:
        self.scheduler.shutdown()
        logger.info("Post scheduler stopped")

    @staticmethod
    def round_slot(
        slot: datetime,
        interval_minutes: int = 15,
    ) -> datetime:
        slot = ensure_timezone_aware(slot)

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
            logger.error("Invalid post provided for scheduling")
            return

        job_id = f"post_{post.id}_{post.repository_id}"

        scheduled_time = ensure_timezone_aware(post.scheduled_time)

        last_post_time = await get_last_post_time()
        if last_post_time:
            time_diff_hours = (scheduled_time - last_post_time).total_seconds() / 3600
            if time_diff_hours < 1.0:
                min_allowed_time = last_post_time + timedelta(hours=1)
                if scheduled_time < min_allowed_time:
                    scheduled_time = min_allowed_time
                    logger.info(
                        "Adjusted scheduled time for post %d to maintain 1-hour interval. "
                        "New time: %s",
                        post.id,
                        scheduled_time,
                    )

        run_date = self.round_slot(scheduled_time)

        if run_date != scheduled_time:
            await update_scheduled_post_time(post.id, run_date)

        try:
            self.scheduler.add_job(
                self._publish_scheduled_post,
                "date",
                run_date=run_date,
                args=[post.id, post_text, banner_buffer.getvalue(), banner_filename],
                id=job_id,
                replace_existing=True,
                misfire_grace_time=3600 * 2,
            )
        except Exception as e:
            logger.error("Failed to schedule post %d: %s", post.id, e)
            raise

        logger.info(
            "Scheduled post for %s at %s (Job ID: %s)",
            post.repository_full_name,
            run_date,
            job_id,
        )

    async def _publish_scheduled_post(
        self, post_id: int, post_text: str, banner_data: bytes, banner_filename: str
    ) -> None:
        try:
            banner_input = BufferedInputFile(banner_data, filename=banner_filename)

            sent_message = await self.bot.send_photo(
                chat_id=self.settings.channel_id,
                photo=banner_input,
                caption=post_text,
            )

            try:
                await update_scheduled_post_as_published(post_id, sent_message.message_id)
                logger.info("Successfully published scheduled post %s", post_id)
            except Exception as db_error:
                logger.error(
                    "Published post %s to channel but failed to update database: %s",
                    post_id,
                    db_error,
                )
                logger.info("Post was sent with message_id: %s", sent_message.message_id)
                raise

        except Exception as e:
            logger.error("Failed to publish scheduled post %s: %s", post_id, e)
            raise

    def cancel_scheduled_post(self, job_id: str) -> None:
        try:
            self.scheduler.remove_job(job_id)
            logger.info("Cancelled scheduled post job: %s", job_id)
        except Exception as e:
            logger.warning("Failed to cancel scheduled post job %s: %s", job_id, e)

    @staticmethod
    async def get_next_available_slot(base_time: datetime | None = None) -> datetime:
        return await get_next_available_slot_with_lock(base_time)
