# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import delete, select

from bot.utils.models import GitHubRepository, GitLabRepository

from .connection import db_manager
from .models import AppSubmission, ScheduledPost

if TYPE_CHECKING:
    from io import BytesIO

logger = logging.getLogger(__name__)


async def has_pending_scheduled_post(repository_id: int) -> bool:
    db = db_manager.get_database()

    async for session in db.get_session():
        stmt = select(ScheduledPost).where(
            ScheduledPost.repository_id == repository_id,
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none() is not None

    return False


def _update_submission_data(
    submission: AppSubmission,
    repository: GitHubRepository | GitLabRepository,
    channel_message_id: int | None = None,
) -> None:
    submission.repository_id = repository.id
    submission.repository_name = repository.name
    submission.repository_owner = repository.owner
    submission.repository_full_name = repository.full_name
    submission.repository_url = repository.url
    submission.description = repository.description
    submission.submitted_at = datetime.now(UTC)
    if channel_message_id is not None:
        submission.channel_message_id = channel_message_id


async def can_submit_app(repository_id: int) -> tuple[bool, datetime | None]:
    db = db_manager.get_database()

    async for session in db.get_session():
        stmt = (
            select(AppSubmission)
            .where(AppSubmission.repository_id == repository_id)
            .order_by(AppSubmission.submitted_at.desc())
        )

        last_submission = (await session.execute(stmt)).scalar_one_or_none()

        if last_submission is None:
            return True, None

        submitted_at = last_submission.submitted_at
        if submitted_at.tzinfo is None:
            submitted_at = submitted_at.replace(tzinfo=UTC)

        three_months_ago = datetime.now(UTC) - timedelta(days=90)
        can_submit = submitted_at < three_months_ago

        return can_submit, submitted_at

    return True, None


async def submit_app(
    repository: GitHubRepository | GitLabRepository, channel_message_id: int | None = None
) -> AppSubmission:
    db = db_manager.get_database()

    async for session in db.get_session():
        stmt = select(AppSubmission).where(AppSubmission.repository_id == repository.id)
        existing_submission = (await session.execute(stmt)).scalar_one_or_none()

        if existing_submission:
            _update_submission_data(existing_submission, repository, channel_message_id)
        else:
            existing_submission = AppSubmission(
                repository_id=repository.id,
                repository_full_name=repository.full_name,
                channel_message_id=channel_message_id,
            )
            _update_submission_data(existing_submission, repository, channel_message_id)
            session.add(existing_submission)

        await session.commit()
        await session.refresh(existing_submission)
        return existing_submission

    msg = "Failed to submit app"
    raise RuntimeError(msg)


async def schedule_post(
    repository: GitHubRepository | GitLabRepository,
    post_text: str,
    banner_buffer: BytesIO,
    banner_filename: str,
    scheduled_time: datetime,
    job_id: str,
) -> ScheduledPost:
    db = db_manager.get_database()

    async for session in db.get_session():
        scheduled_post = ScheduledPost(
            repository_id=repository.id,
            repository_name=repository.name,
            repository_full_name=repository.full_name,
            repository_owner=repository.owner,
            repository_url=repository.url,
            description=repository.description,
            post_text=post_text,
            banner_data=banner_buffer.getvalue(),
            banner_filename=banner_filename,
            scheduled_time=scheduled_time,
            job_id=job_id,
        )

        session.add(scheduled_post)
        await session.commit()
        await session.refresh(scheduled_post)
        return scheduled_post

    msg = "Failed to schedule post"
    raise RuntimeError(msg)


async def get_scheduled_posts_after_time(
    start_time: datetime, end_time: datetime
) -> list[ScheduledPost]:
    db = db_manager.get_database()

    async for session in db.get_session():
        stmt = (
            select(ScheduledPost)
            .where(
                ScheduledPost.scheduled_time >= start_time,
                ScheduledPost.scheduled_time <= end_time,
            )
            .distinct()
            .order_by(ScheduledPost.scheduled_time)
        )

        result = await session.execute(stmt)
        return list(result.scalars().all())

    return []


async def update_scheduled_post_as_published(post_id: int, channel_message_id: int) -> None:
    db = db_manager.get_database()

    async for session in db.get_session():
        try:
            stmt = select(ScheduledPost).where(ScheduledPost.id == post_id)
            scheduled_post = (await session.execute(stmt)).scalar_one_or_none()

            if not scheduled_post:
                logger.warning("Scheduled post %d not found when marking as published", post_id)
                return

            existing_app_stmt = select(AppSubmission).where(
                AppSubmission.repository_id == scheduled_post.repository_id
            )
            existing_app = (await session.execute(existing_app_stmt)).scalar_one_or_none()

            if existing_app:
                existing_app.repository_name = scheduled_post.repository_name
                existing_app.repository_owner = scheduled_post.repository_owner
                existing_app.repository_full_name = scheduled_post.repository_full_name
                existing_app.repository_url = scheduled_post.repository_url
                existing_app.description = scheduled_post.description
                existing_app.submitted_at = datetime.now(UTC)
                existing_app.channel_message_id = channel_message_id
            else:
                new_app = AppSubmission(
                    repository_id=scheduled_post.repository_id,
                    repository_name=scheduled_post.repository_name,
                    repository_owner=scheduled_post.repository_owner,
                    repository_full_name=scheduled_post.repository_full_name,
                    repository_url=scheduled_post.repository_url,
                    description=scheduled_post.description,
                    submitted_at=datetime.now(UTC),
                    channel_message_id=channel_message_id,
                )
                session.add(new_app)

            await session.flush()

            await session.delete(scheduled_post)
            await session.commit()

        except Exception as e:
            await session.rollback()
            logger.error("Failed to mark scheduled post %d as published: %s", post_id, e)
            raise


async def get_last_post_time() -> datetime | None:
    db = db_manager.get_database()

    async for session in db.get_session():
        app_stmt = (
            select(AppSubmission)
            .where(AppSubmission.channel_message_id.isnot(None))
            .order_by(AppSubmission.submitted_at.desc())
            .limit(1)
        )
        last_app = (await session.execute(app_stmt)).scalar_one_or_none()

        if last_app:
            app_time = last_app.submitted_at
            if app_time.tzinfo is None:
                app_time = app_time.replace(tzinfo=UTC)
            else:
                app_time = app_time.astimezone(UTC)
            return app_time

        return None

    return None


async def get_next_available_slot_with_lock(base_time: datetime | None = None) -> datetime:
    if base_time is None:
        base_time = datetime.now(UTC)

    if base_time.tzinfo is None:
        base_time = base_time.replace(tzinfo=UTC)

    db = db_manager.get_database()

    async for session in db.get_session():
        async with session.begin():
            last_post_time = await get_last_post_time()

            if last_post_time is None:
                return base_time

            if last_post_time.tzinfo is None:
                last_post_time = last_post_time.replace(tzinfo=UTC)
            else:
                last_post_time = last_post_time.astimezone(UTC)

            time_since_last = base_time - last_post_time
            if time_since_last >= timedelta(hours=1):
                return base_time

            next_slot = last_post_time + timedelta(hours=1)

            max_attempts = 24
            attempts = 0

            while attempts < max_attempts:
                future_posts = await get_scheduled_posts_after_time(
                    next_slot - timedelta(minutes=30), next_slot + timedelta(minutes=30)
                )

                if not future_posts:
                    break

                next_slot += timedelta(hours=1)
                attempts += 1

            return next_slot

    return base_time


async def cleanup_orphaned_scheduled_posts(days_old: int = 30) -> int:
    db = db_manager.get_database()

    cutoff_date = datetime.now(UTC) - timedelta(days=days_old)

    async for session in db.get_session():
        stmt = select(ScheduledPost).where(
            ScheduledPost.scheduled_time < cutoff_date,
        )

        orphaned_posts = (await session.execute(stmt)).scalars().all()
        count = len(orphaned_posts)

        if count > 0:
            delete_stmt = delete(ScheduledPost).where(
                ScheduledPost.scheduled_time < cutoff_date,
            )

            await session.execute(delete_stmt)
            await session.commit()

        return count

    return 0


async def update_scheduled_post_time(post_id: int, new_scheduled_time: datetime) -> None:
    db = db_manager.get_database()

    async for session in db.get_session():
        stmt = select(ScheduledPost).where(ScheduledPost.id == post_id)
        scheduled_post = (await session.execute(stmt)).scalar_one_or_none()

        if scheduled_post:
            scheduled_post.scheduled_time = new_scheduled_time
            await session.commit()
