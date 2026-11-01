"""platform settings: the showcase workspace that feeds the public site's live preview

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-01 20:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("platform_settings") as batch:
        batch.add_column(sa.Column("showcase_workspace_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key(
            "fk_platform_settings_showcase_workspace", "workspaces", ["showcase_workspace_id"], ["id"], ondelete="SET NULL"
        )


def downgrade() -> None:
    with op.batch_alter_table("platform_settings") as batch:
        batch.drop_constraint("fk_platform_settings_showcase_workspace", type_="foreignkey")
        batch.drop_column("showcase_workspace_id")
