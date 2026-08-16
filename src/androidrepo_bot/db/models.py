from datetime import datetime
from typing import Annotated, Literal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

type IntegerPrimaryKey = Annotated[int, mapped_column(Integer, primary_key=True, autoincrement=True)]
type Timestamp = Annotated[datetime, mapped_column(DateTime(timezone=True), nullable=False)]
type PublicationOperationStatus = Literal["copying", "compensating", "completed", "uncertain", "failed", "abandoned"]


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class RepositoryApp(Base):
    __tablename__ = "repository_apps"
    __table_args__ = (
        UniqueConstraint("provider", "provider_repository_id", name="uq_repository_apps_provider_id"),
        CheckConstraint("first_seen_at <= last_seen_at", name="seen_order"),
    )

    id: Mapped[IntegerPrimaryKey]
    provider: Mapped[str] = mapped_column(String(32))
    provider_repository_id: Mapped[str] = mapped_column(String(128))
    current_namespace: Mapped[str] = mapped_column(String(512))
    current_name: Mapped[str] = mapped_column(String(255))
    current_url: Mapped[str] = mapped_column(String(2048))
    display_name: Mapped[str] = mapped_column(String(255))
    first_seen_at: Mapped[Timestamp]
    last_seen_at: Mapped[Timestamp]


class RepositoryAlias(Base):
    __tablename__ = "repository_aliases"
    __table_args__ = (
        UniqueConstraint("repository_app_id", "full_name", "url", name="uq_repository_aliases_repository_value"),
    )

    id: Mapped[IntegerPrimaryKey]
    repository_app_id: Mapped[int] = mapped_column(ForeignKey("repository_apps.id", ondelete="CASCADE"), nullable=False)
    namespace: Mapped[str] = mapped_column(String(512))
    name: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(768))
    url: Mapped[str] = mapped_column(String(2048))
    observed_at: Mapped[Timestamp]


class PublishedPost(Base):
    __tablename__ = "published_posts"
    __table_args__ = (
        Index("ix_published_posts_repository_published_at", "repository_app_id", "published_at"),
        UniqueConstraint("channel_id", "channel_message_id", name="uq_published_posts_channel_message"),
    )

    id: Mapped[IntegerPrimaryKey]
    repository_app_id: Mapped[int] = mapped_column(ForeignKey("repository_apps.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(String(255))
    tags: Mapped[list[str]] = mapped_column(ARRAY(String(64)))
    created_by_user_id: Mapped[int] = mapped_column(BigInteger)
    channel_id: Mapped[int] = mapped_column(BigInteger)
    channel_message_id: Mapped[int] = mapped_column(BigInteger)
    published_at: Mapped[Timestamp]


class PublicationOperation(Base):
    __tablename__ = "publication_operations"
    __table_args__ = (
        Index("ix_publication_operations_status_lease", "status", "lease_expires_at"),
        Index(
            "uq_publication_operations_open_repository",
            "repository_app_id",
            unique=True,
            postgresql_where=text("status IN ('copying', 'compensating', 'uncertain')"),
        ),
        CheckConstraint(
            "(status = 'copying' AND lease_expires_at IS NOT NULL "
            "AND channel_message_id IS NULL AND published_at IS NULL AND published_post_id IS NULL) OR "
            "(status = 'compensating' AND lease_expires_at IS NULL "
            "AND channel_message_id IS NOT NULL AND published_at IS NOT NULL AND published_post_id IS NULL) OR "
            "(status = 'completed' AND lease_expires_at IS NULL "
            "AND channel_message_id IS NOT NULL AND published_at IS NOT NULL AND published_post_id IS NOT NULL) OR "
            "(status IN ('uncertain', 'failed') AND lease_expires_at IS NULL "
            "AND channel_message_id IS NULL AND published_at IS NULL AND published_post_id IS NULL) OR "
            "(status = 'abandoned' AND lease_expires_at IS NULL AND published_post_id IS NULL "
            "AND ((channel_message_id IS NULL AND published_at IS NULL) OR "
            "(channel_message_id IS NOT NULL AND published_at IS NOT NULL)))",
            name="state_shape",
        ),
    )

    id: Mapped[IntegerPrimaryKey]
    repository_app_id: Mapped[int] = mapped_column(ForeignKey("repository_apps.id", ondelete="CASCADE"), nullable=False)
    source_chat_id: Mapped[int] = mapped_column(BigInteger)
    source_message_id: Mapped[int] = mapped_column(BigInteger)
    channel_id: Mapped[int] = mapped_column(BigInteger)
    actor_user_id: Mapped[int] = mapped_column(BigInteger)
    title: Mapped[str] = mapped_column(String(255))
    tags: Mapped[list[str]] = mapped_column(ARRAY(String(64)))
    status: Mapped[PublicationOperationStatus] = mapped_column(String(32))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    channel_message_id: Mapped[int | None] = mapped_column(BigInteger)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_post_id: Mapped[int | None] = mapped_column(
        ForeignKey("published_posts.id", ondelete="RESTRICT"), nullable=True, unique=True
    )
    created_at: Mapped[Timestamp]
    updated_at: Mapped[Timestamp]


class PostAttempt(Base):
    __tablename__ = "post_attempts"
    __table_args__ = (
        Index("ix_post_attempts_repository_attempted_at", "repository_app_id", "attempted_at"),
        CheckConstraint(
            "status = 'blocked' AND blocked_until IS NOT NULL AND reason IS NOT NULL AND reason = 'cooldown'",
            name="blocked_shape",
        ),
    )

    id: Mapped[IntegerPrimaryKey]
    repository_app_id: Mapped[int | None] = mapped_column(
        ForeignKey("repository_apps.id", ondelete="SET NULL"), nullable=True
    )
    provider: Mapped[str] = mapped_column(String(32))
    namespace: Mapped[str] = mapped_column(String(512))
    name: Mapped[str] = mapped_column(String(255))
    url: Mapped[str] = mapped_column(String(2048))
    requested_by_user_id: Mapped[int] = mapped_column(BigInteger)
    attempted_at: Mapped[Timestamp]
    status: Mapped[str] = mapped_column(String(32))
    blocked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str | None] = mapped_column(String(255))
