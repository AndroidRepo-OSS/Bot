from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "20260812_0003"
down_revision: str | None = "20260711_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "publication_operations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("repository_app_id", sa.Integer(), nullable=False),
        sa.Column("source_chat_id", sa.BigInteger(), nullable=False),
        sa.Column("source_message_id", sa.BigInteger(), nullable=False),
        sa.Column("channel_id", sa.BigInteger(), nullable=False),
        sa.Column("actor_user_id", sa.BigInteger(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("tags", postgresql.ARRAY(sa.String(length=64)), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("channel_message_id", sa.BigInteger(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_post_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
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
            name=op.f("ck_publication_operations_state_shape"),
        ),
        sa.ForeignKeyConstraint(["published_post_id"], ["published_posts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["repository_app_id"], ["repository_apps.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("published_post_id", name="uq_publication_operations_published_post_id"),
    )
    op.create_index(
        "ix_publication_operations_status_lease", "publication_operations", ["status", "lease_expires_at"], unique=False
    )
    op.create_index(
        "uq_publication_operations_open_repository",
        "publication_operations",
        ["repository_app_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('copying', 'compensating', 'uncertain')"),
    )


def downgrade() -> None:
    op.drop_index("uq_publication_operations_open_repository", table_name="publication_operations")
    op.drop_index("ix_publication_operations_status_lease", table_name="publication_operations")
    op.drop_table("publication_operations")
