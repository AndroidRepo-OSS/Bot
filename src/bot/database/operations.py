# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from bot.utils.models import GitHubRepository

from .connection import db_manager
from .models import AppSubmission


def _update_submission_data(
    submission: AppSubmission, repository: GitHubRepository, channel_message_id: int | None = None
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
    repository: GitHubRepository, channel_message_id: int | None = None
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
