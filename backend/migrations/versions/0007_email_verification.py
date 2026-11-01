"""email verification

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-31 14:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True))
    # Accounts that exist today were created by an admin or signed up before confirmation existed: treat as confirmed.
    op.execute("UPDATE users SET email_verified_at = now()")


def downgrade() -> None:
    op.drop_column("users", "email_verified_at")
