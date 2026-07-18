from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "20260625_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "repository_apps",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("provider_repository_id", sa.String(length=128), nullable=False),
        sa.Column("current_namespace", sa.String(length=512), nullable=False),
        sa.Column("current_name", sa.String(length=255), nullable=False),
        sa.Column("current_url", sa.String(length=2048), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "provider_repository_id", name="uq_repository_apps_provider_id"),
    )
    op.create_table(
        "repository_aliases",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("repository_app_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("namespace", sa.String(length=512), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("full_name", sa.String(length=768), nullable=False),
        sa.Column("url", sa.String(length=2048), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["repository_app_id"], ["repository_apps.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "full_name", name="uq_repository_aliases_provider_full_name"),
        sa.UniqueConstraint("provider", "url", name="uq_repository_aliases_provider_url"),
    )
    op.create_table(
        "post_attempts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("repository_app_id", sa.Integer(), nullable=True),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("namespace", sa.String(length=512), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("url", sa.String(length=2048), nullable=False),
        sa.Column("requested_by_user_id", sa.BigInteger(), nullable=False),
        sa.Column("attempted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("blocked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reason", sa.String(length=255), nullable=True),
        sa.ForeignKeyConstraint(["repository_app_id"], ["repository_apps.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_post_attempts_repository_attempted_at", "post_attempts", ["repository_app_id", "attempted_at"], unique=False
    )
    op.create_table(
        "published_posts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("repository_app_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("tags", postgresql.ARRAY(sa.String(length=64)), nullable=False),
        sa.Column("created_by_user_id", sa.BigInteger(), nullable=False),
        sa.Column("channel_id", sa.BigInteger(), nullable=False),
        sa.Column("channel_message_id", sa.BigInteger(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["repository_app_id"], ["repository_apps.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_published_posts_channel_message", "published_posts", ["channel_id", "channel_message_id"], unique=False
    )
    op.create_index(
        "ix_published_posts_repository_published_at",
        "published_posts",
        ["repository_app_id", "published_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_published_posts_repository_published_at", table_name="published_posts")
    op.drop_index("ix_published_posts_channel_message", table_name="published_posts")
    op.drop_table("published_posts")
    op.drop_index("ix_post_attempts_repository_attempted_at", table_name="post_attempts")
    op.drop_table("post_attempts")
    op.drop_table("repository_aliases")
    op.drop_table("repository_apps")
