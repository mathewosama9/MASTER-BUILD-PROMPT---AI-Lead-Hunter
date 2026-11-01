"""credit packages: a "featured" flag and starter EGP packages

The pricing page showed "packages are being finalised" because packages could only be created through the admin
API. Seeds three EGP packages when none exist; the platform admin edits prices and names afterwards.

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-01 18:00:00.000000
"""

import uuid
from collections.abc import Sequence
from decimal import Decimal

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (name_ar, name_en, credits, price EGP, featured, sort). Basic credits cost the platform ~1-2 EGP in search,
# scraping and AI, so no package goes below 2 EGP per credit.
PACKAGES = [
    ("باقة البداية", "Starter", 250, Decimal("750"), False, 10),
    ("باقة النمو", "Growth", 1000, Decimal("2500"), True, 20),
    ("باقة الوكالات", "Agency", 3000, Decimal("6000"), False, 30),
]


def upgrade() -> None:
    op.add_column(
        "credit_packages", sa.Column("featured", sa.Boolean(), nullable=False, server_default=sa.false())
    )
    conn = op.get_bind()
    if conn.scalar(sa.text("SELECT count(*) FROM credit_packages")):
        return
    table = sa.table(
        "credit_packages",
        sa.column("id", sa.Uuid()),
        sa.column("name_ar", sa.String()),
        sa.column("name_en", sa.String()),
        sa.column("credits", sa.Integer()),
        sa.column("price", sa.Numeric(12, 2)),
        sa.column("currency", sa.String()),
        sa.column("active", sa.Boolean()),
        sa.column("featured", sa.Boolean()),
        sa.column("sort", sa.Integer()),
    )
    op.bulk_insert(
        table,
        [
            {
                "id": uuid.uuid4(),
                "name_ar": ar,
                "name_en": en,
                "credits": credits,
                "price": price,
                "currency": "EGP",
                "active": True,
                "featured": featured,
                "sort": sort,
            }
            for ar, en, credits, price, featured, sort in PACKAGES
        ],
    )


def downgrade() -> None:
    op.drop_column("credit_packages", "featured")
