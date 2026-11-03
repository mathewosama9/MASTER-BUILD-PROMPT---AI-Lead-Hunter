"""user presence and admin control: last seen, the browser behind each device signal, private admin notes

Revision ID: 0017
Revises: 0016
Create Date: 2026-11-03 00:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("last_seen_ip", sa.String(64), nullable=True))
    op.add_column("users", sa.Column("admin_notes", sa.Text(), nullable=True))
    op.add_column("account_signals", sa.Column("user_agent", sa.String(400), nullable=True))
    op.add_column("account_signals", sa.Column("ip", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("account_signals", "ip")
    op.drop_column("account_signals", "user_agent")
    op.drop_column("users", "admin_notes")
    op.drop_column("users", "last_seen_ip")
    op.drop_column("users", "last_seen_at")
