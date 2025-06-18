# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from aiogram import Bot
from aiogram.types import BufferedInputFile
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from bot.config import Settings
from bot.database import (
    cleanup_old_published_posts,
    cleanup_orphaned_scheduled_posts,
    get_next_available_slot_with_lock,
    get_scheduled_posts_after_time,
    get_scheduled_posts_in_range,
    update_scheduled_post_as_published,
    update_scheduled_post_time,
)
from bot.database.models import ScheduledPost

if TYPE_CHECKING:
    from io import BytesIO

logger = logging.getLogger(__name__)


class PostScheduler:
    def __init__(self, bot: Bot, settings: Settings) -> None:
        self.bot = bot
        self.scheduler = AsyncIOScheduler(timezone="UTC")
        self.settings = settings

    async def start(self) -> None:
        self.scheduler.start()
        self.scheduler.add_job(
            self._cleanup_old_posts,
            "interval",
            hours=24,
            id="cleanup_old_posts",
            replace_existing=True,
        )
        await self._restore_scheduled_jobs()
        logger.info("Post scheduler started")

    @staticmethod
    async def _cleanup_old_posts() -> None:
        try:
            published_count = await cleanup_old_published_posts(days_old=7)
            orphaned_count = await cleanup_orphaned_scheduled_posts(days_old=3)

            if published_count > 0:
                logger.info("Daily cleanup: %d published posts", published_count)
            if orphaned_count > 0:
                logger.info("Daily cleanup: %d orphaned scheduled posts", orphaned_count)

        except Exception as e:
            logger.error("Failed to cleanup old posts: %s", e)

    async def stop(self) -> None:
        self.scheduler.shutdown()
        logger.info("Post scheduler stopped")

    @staticmethod
    def _round_slot(
        slot: datetime,
        interval_minutes: int = 15,
    ) -> datetime:
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
        job_id = f"post_{post.id}_{post.repository_id}"
        run_date = self._round_slot(post.scheduled_time)

        if run_date != post.scheduled_time:
            await update_scheduled_post_time(post.id, run_date)

        self.scheduler.add_job(
            self._publish_scheduled_post,
            "date",
            run_date=run_date,
            args=[post.id, post_text, banner_buffer.getvalue(), banner_filename],
            id=job_id,
            replace_existing=True,
            misfire_grace_time=3600 * 2,
        )

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

            await update_scheduled_post_as_published(post_id, sent_message.message_id)
            logger.info("Successfully published scheduled post %s", post_id)

        except Exception as e:
            logger.error("Failed to publish scheduled post %s: %s", post_id, e)

    def cancel_scheduled_post(self, job_id: str) -> None:
        try:
            self.scheduler.remove_job(job_id)
            logger.info("Cancelled scheduled post job: %s", job_id)
        except Exception as e:
            logger.warning("Failed to cancel scheduled post job %s: %s", job_id, e)

    @staticmethod
    async def get_next_available_slot(base_time: datetime | None = None) -> datetime:
        return await get_next_available_slot_with_lock(base_time)

    async def _restore_scheduled_jobs(self) -> None:
        try:
            current_time = datetime.now(UTC)
            future_time = current_time + timedelta(days=365)
            past_time = current_time - timedelta(hours=24)

            pending_posts = await get_scheduled_posts_after_time(current_time, future_time)
            missed_posts = await get_scheduled_posts_in_range(
                past_time, current_time, include_past=True
            )

            restored_count = 0
            missed_count = 0

            for post in pending_posts:
                job_id = f"post_{post.id}_{post.repository_id}"
                run_date = self._round_slot(post.scheduled_time)

                self.scheduler.add_job(
                    self._publish_scheduled_post,
                    "date",
                    run_date=run_date,
                    args=[post.id, post.post_text, post.banner_data, post.banner_filename],
                    id=job_id,
                    replace_existing=True,
                    misfire_grace_time=3600 * 2,
                )
                restored_count += 1

            for post in missed_posts:
                await self._handle_missed_post(post)
                missed_count += 1

            logger.info("Restored %d scheduled post jobs", restored_count)
            if missed_count > 0:
                logger.info("Processed %d missed posts", missed_count)

        except Exception as e:
            logger.error("Failed to restore scheduled jobs: %s", e)

    async def _handle_missed_post(self, post: ScheduledPost) -> None:
        try:
            current_time = datetime.now(UTC)
            time_diff = current_time - post.scheduled_time

            if time_diff <= timedelta(hours=2):
                logger.info(
                    "Publishing missed post %d (scheduled %d minutes ago)",
                    post.id,
                    int(time_diff.total_seconds() / 60),
                )
                await self._publish_scheduled_post(
                    post.id, post.post_text, post.banner_data, post.banner_filename
                )
            else:
                logger.warning(
                    "Skipping severely delayed post %d (scheduled %d hours ago)",
                    post.id,
                    int(time_diff.total_seconds() / 3600),
                )
                await self._reschedule_missed_post(post)

        except Exception as e:
            logger.error("Failed to handle missed post %d: %s", post.id, e)

    async def _reschedule_missed_post(self, post: ScheduledPost) -> None:
        try:
            next_slot = await self.get_next_available_slot()
            next_slot = self._round_slot(next_slot)
            job_id = f"post_{post.id}_{post.repository_id}"

            await update_scheduled_post_time(post.id, next_slot)

            self.scheduler.add_job(
                self._publish_scheduled_post,
                "date",
                run_date=next_slot,
                args=[post.id, post.post_text, post.banner_data, post.banner_filename],
                id=job_id,
                replace_existing=True,
                misfire_grace_time=3600 * 2,
            )

            logger.info(
                "Rescheduled missed post %d to %s",
                post.id,
                next_slot.strftime("%Y-%m-%d %H:%M UTC"),
            )

        except Exception as e:
            logger.error("Failed to reschedule missed post %d: %s", post.id, e)
