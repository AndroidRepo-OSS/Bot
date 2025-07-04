# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2025 Hitalo M. <https://github.com/HitaloM>

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, LargeBinary, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    pass


class AppSubmission(Base):
    __tablename__ = "app_submissions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    repository_id: Mapped[int] = mapped_column(nullable=False, unique=True, index=True)
    repository_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    repository_full_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    repository_owner: Mapped[str] = mapped_column(String(100), nullable=False)
    repository_url: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=func.now(), server_default=func.now()
    )
    channel_message_id: Mapped[int | None] = mapped_column(nullable=True)

    def __repr__(self) -> str:
        return (
            f"<AppSubmission(id={self.id}, repo_id={self.repository_id}, "
            f"repo='{self.repository_full_name}', submitted_at='{self.submitted_at}')>"
        )


class ScheduledPost(Base):
    __tablename__ = "scheduled_posts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    repository_id: Mapped[int] = mapped_column(nullable=False, index=True)
    repository_name: Mapped[str] = mapped_column(String(255), nullable=False)
    repository_full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    repository_owner: Mapped[str] = mapped_column(String(100), nullable=False)
    repository_url: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    post_text: Mapped[str] = mapped_column(Text, nullable=False)
    banner_data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    banner_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    scheduled_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    channel_message_id: Mapped[int | None] = mapped_column(nullable=True)
    job_id: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)

    def __repr__(self) -> str:
        return (
            f"<ScheduledPost(id={self.id}, repo='{self.repository_full_name}', "
            f"scheduled_time='{self.scheduled_time}')>"
        )
