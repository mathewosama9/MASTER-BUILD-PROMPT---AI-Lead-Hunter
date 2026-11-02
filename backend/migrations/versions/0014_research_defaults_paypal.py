"""platform research defaults (admin-managed campaign settings); PayPal top-ups; store currency USD

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-02 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("platform_settings") as batch:
        batch.add_column(
            sa.Column(
                "research_defaults",
                sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
                nullable=False,
                server_default="{}",
            )
        )
    with op.batch_alter_table("topup_requests") as batch:
        batch.add_column(sa.Column("provider_order_id", sa.String(64), nullable=True))
        batch.add_column(sa.Column("provider_capture_id", sa.String(64), nullable=True))
        batch.create_unique_constraint("uq_topup_requests_provider_order_id", ["provider_order_id"])
    # The store sells in US dollars. Prices keep their numbers: the admin sets the dollar prices in Admin → Packages.
    op.execute("UPDATE credit_packages SET currency = 'USD'")


def downgrade() -> None:
    op.execute("UPDATE credit_packages SET currency = 'EGP'")
    with op.batch_alter_table("topup_requests") as batch:
        batch.drop_constraint("uq_topup_requests_provider_order_id", type_="unique")
        batch.drop_column("provider_capture_id")
        batch.drop_column("provider_order_id")
    with op.batch_alter_table("platform_settings") as batch:
        batch.drop_column("research_defaults")
