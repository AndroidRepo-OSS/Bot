# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from bot.utils.models import GitHubRepository

from .connection import db_manager
from .models import AppSubmission


async def can_submit_app(repository_full_name: str) -> tuple[bool, datetime | None]:
    db = db_manager.get_database()

    async for session in db.get_session():
        stmt = (
            select(AppSubmission)
            .where(AppSubmission.repository_full_name == repository_full_name)
            .order_by(AppSubmission.submitted_at.desc())
        )

        result = await session.execute(stmt)
        last_submission = result.scalar_one_or_none()

        if last_submission is None:
            return True, None

        three_months_ago = datetime.now(UTC) - timedelta(days=90)

        submitted_at = last_submission.submitted_at
        if submitted_at.tzinfo is None:
            submitted_at = submitted_at.replace(tzinfo=UTC)

        if submitted_at >= three_months_ago:
            return False, submitted_at

        return True, submitted_at

    return True, None


async def submit_app(
    repository: GitHubRepository, channel_message_id: int | None = None
) -> AppSubmission:
    db = db_manager.get_database()

    async for session in db.get_session():
        app_submission = AppSubmission(
            repository_name=repository.name,
            repository_full_name=repository.full_name,
            repository_owner=repository.owner,
            repository_url=repository.url,
            description=repository.description,
            channel_message_id=channel_message_id,
            submitted_at=datetime.now(UTC),
        )

        session.add(app_submission)

        try:
            await session.commit()
            await session.refresh(app_submission)
            return app_submission
        except IntegrityError as e:
            await session.rollback()
            error_msg = f"App '{repository.full_name}' already exists in database"
            raise ValueError(error_msg) from e

    msg = "Failed to submit app"
    raise RuntimeError(msg)
