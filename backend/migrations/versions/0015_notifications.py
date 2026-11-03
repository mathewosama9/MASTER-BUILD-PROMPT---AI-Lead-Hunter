"""notifications: in-app inbox, email/Telegram outbox, admin broadcasts, user preferences and admin policy

Revision ID: 0015
Revises: 0014
Create Date: 2026-11-02 18:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")
NOW = sa.text("now()")


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "broadcasts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("title_ar", sa.String(300), nullable=False),
        sa.Column("title_en", sa.String(300), nullable=False),
        sa.Column("body_ar", sa.Text(), nullable=False),
        sa.Column("body_en", sa.Text(), nullable=False),
        sa.Column("link", sa.String(500), nullable=True),
        sa.Column("audience", JSON, nullable=False),
        sa.Column("channels", JSON, nullable=False),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("recipients", sa.Integer(), server_default="0", nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name="fk_broadcasts_created_by_users", ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_broadcasts"),
    )
    op.create_table(
        "notifications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("link", sa.String(500), nullable=True),
        sa.Column("params", JSON, nullable=False),
        sa.Column("broadcast_id", sa.Uuid(), nullable=True),
        sa.Column("in_app", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_notifications_user_id_users", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], name="fk_notifications_workspace_id_workspaces", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["broadcast_id"], ["broadcasts.id"], name="fk_notifications_broadcast_id_broadcasts", ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_notifications"),
    )
    op.create_index("ix_notifications_kind", "notifications", ["kind"])
    op.create_index("ix_notifications_user_read_created", "notifications", ["user_id", "read_at", "created_at"])
    op.create_table(
        "notification_deliveries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("notification_id", sa.Uuid(), nullable=False),
        sa.Column("channel", sa.String(16), nullable=False),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_error", sa.String(500), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["notification_id"],
            ["notifications.id"],
            name="fk_notification_deliveries_notification_id_notifications",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_notification_deliveries"),
    )
    op.create_index("ix_notification_deliveries_notification_id", "notification_deliveries", ["notification_id"])
    op.create_index("ix_notification_deliveries_due", "notification_deliveries", ["status", "next_attempt_at"])
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("notification_prefs", JSON, nullable=False, server_default="{}"))
    with op.batch_alter_table("platform_settings") as batch:
        batch.add_column(sa.Column("notification_policy", JSON, nullable=False, server_default="{}"))
        batch.add_column(sa.Column("email_rate_per_minute", sa.Integer(), nullable=False, server_default="20"))


def downgrade() -> None:
    with op.batch_alter_table("platform_settings") as batch:
        batch.drop_column("email_rate_per_minute")
        batch.drop_column("notification_policy")
    with op.batch_alter_table("users") as batch:
        batch.drop_column("notification_prefs")
    op.drop_table("notification_deliveries")
    op.drop_table("notifications")
    op.drop_table("broadcasts")
