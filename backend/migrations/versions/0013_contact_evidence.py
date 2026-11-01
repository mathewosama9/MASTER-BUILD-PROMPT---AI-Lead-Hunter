"""business contacts: evidence (which sources confirmed a value; proof behind a verified decision maker)

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-01 22:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("business_contacts") as batch:
        batch.add_column(
            sa.Column(
                "evidence", sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"), nullable=True
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("business_contacts") as batch:
        batch.drop_column("evidence")
