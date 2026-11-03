"""signup review: nationality, admin approval of self-signups, and account signals for duplicate detection

Revision ID: 0016
Revises: 0015
Create Date: 2026-11-02 21:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NOW = sa.text("now()")


def upgrade() -> None:
    op.add_column("users", sa.Column("nationality", sa.String(2), nullable=True))
    # Everyone already registered stays approved; only new self-signups start as pending.
    op.add_column(
        "users", sa.Column("approval_status", sa.String(16), server_default="approved", nullable=False)
    )
    op.create_index("ix_users_approval_status", "users", ["approval_status"])
    op.add_column("users", sa.Column("reviewed_by", sa.Uuid(), nullable=True))
    op.create_foreign_key("fk_users_reviewed_by_users", "users", "users", ["reviewed_by"], ["id"], ondelete="SET NULL")
    op.add_column("users", sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("review_note", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("signup_ip", sa.String(64), nullable=True))
    op.add_column(
        "platform_settings", sa.Column("signup_review", sa.Boolean(), server_default="true", nullable=False)
    )

    op.create_table(
        "account_signals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("value", sa.String(255), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_account_signals_user_id_users", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_account_signals"),
        sa.UniqueConstraint("user_id", "kind", "value", name="uq_account_signals_user_id_kind_value"),
    )
    op.create_index("ix_account_signals_user_id", "account_signals", ["user_id"])
    op.create_index("ix_account_signals_kind_value", "account_signals", ["kind", "value"])


def downgrade() -> None:
    op.drop_table("account_signals")
    op.drop_column("platform_settings", "signup_review")
    for col in ("signup_ip", "review_note", "reviewed_at"):
        op.drop_column("users", col)
    op.drop_constraint("fk_users_reviewed_by_users", "users", type_="foreignkey")
    op.drop_column("users", "reviewed_by")
    op.drop_index("ix_users_approval_status", "users")
    op.drop_column("users", "approval_status")
    op.drop_column("users", "nationality")
