from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op

if TYPE_CHECKING:
    from collections.abc import Sequence

revision: str = "20260711_0002"
down_revision: str | None = "20260625_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("uq_repository_aliases_provider_full_name", "repository_aliases", type_="unique")
    op.drop_constraint("uq_repository_aliases_provider_url", "repository_aliases", type_="unique")
    op.create_unique_constraint(
        "uq_repository_aliases_repository_value", "repository_aliases", ["repository_app_id", "full_name", "url"]
    )
    op.drop_column("repository_aliases", "provider")

    op.create_check_constraint(
        op.f("ck_repository_apps_seen_order"), "repository_apps", "first_seen_at <= last_seen_at"
    )
    op.create_check_constraint(
        op.f("ck_post_attempts_blocked_shape"),
        "post_attempts",
        "status = 'blocked' AND blocked_until IS NOT NULL AND reason IS NOT NULL AND reason = 'cooldown'",
    )

    op.execute(
        sa.text(
            """
            DELETE FROM published_posts AS duplicate
            USING published_posts AS original
            WHERE duplicate.channel_id = original.channel_id
              AND duplicate.channel_message_id = original.channel_message_id
              AND duplicate.id > original.id
            """
        )
    )
    op.drop_index("ix_published_posts_channel_message", table_name="published_posts")
    op.create_unique_constraint(
        "uq_published_posts_channel_message", "published_posts", ["channel_id", "channel_message_id"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_published_posts_channel_message", "published_posts", type_="unique")
    op.create_index(
        "ix_published_posts_channel_message", "published_posts", ["channel_id", "channel_message_id"], unique=False
    )
    op.drop_constraint(op.f("ck_post_attempts_blocked_shape"), "post_attempts", type_="check")
    op.drop_constraint(op.f("ck_repository_apps_seen_order"), "repository_apps", type_="check")

    op.add_column("repository_aliases", sa.Column("provider", sa.String(length=32), nullable=True))
    op.execute(
        sa.text(
            """
            UPDATE repository_aliases AS alias
            SET provider = repository.provider
            FROM repository_apps AS repository
            WHERE alias.repository_app_id = repository.id
            """
        )
    )
    op.drop_constraint("uq_repository_aliases_repository_value", "repository_aliases", type_="unique")
    _deduplicate_legacy_aliases("full_name")
    _deduplicate_legacy_aliases("url")
    op.alter_column("repository_aliases", "provider", existing_type=sa.String(length=32), nullable=False)
    op.create_unique_constraint(
        "uq_repository_aliases_provider_full_name", "repository_aliases", ["provider", "full_name"]
    )
    op.create_unique_constraint("uq_repository_aliases_provider_url", "repository_aliases", ["provider", "url"])


def _deduplicate_legacy_aliases(value_column: str) -> None:
    if value_column not in {"full_name", "url"}:
        msg = "unsupported legacy alias column"
        raise ValueError(msg)
    op.execute(
        sa.text(
            f"""
            DELETE FROM repository_aliases
            WHERE id IN (
                SELECT id
                FROM (
                    SELECT
                        id,
                        row_number() OVER (
                            PARTITION BY provider, {value_column}
                            ORDER BY observed_at DESC, id DESC
                        ) AS duplicate_rank
                    FROM repository_aliases
                ) AS ranked_aliases
                WHERE duplicate_rank > 1
            )
            """
        )
    )
