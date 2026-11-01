"""platform-wide provider configuration: API keys and linked accounts managed by platform admins only

Rows with workspace_id NULL apply to every workspace. The keys the platform admins had saved in their own
workspaces become the platform rows, so campaigns of every customer keep working with them.

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-01 15:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("provider_configurations", "workspace_id", existing_type=sa.Uuid(), nullable=True)
    op.create_index(
        "uq_provider_configurations_platform_key",
        "provider_configurations",
        ["provider_key"],
        unique=True,
        postgresql_where=sa.text("workspace_id IS NULL"),
    )
    # Promote the platform admins' own provider rows (oldest admin workspace first) to platform rows.
    op.execute(
        """
        WITH admin_rows AS (
            SELECT DISTINCT ON (pc.provider_key) pc.id
            FROM provider_configurations pc
            JOIN workspace_members wm ON wm.workspace_id = pc.workspace_id
            JOIN users u ON u.id = wm.user_id
            WHERE u.is_superuser
            ORDER BY pc.provider_key, (pc.encrypted_credentials IS NULL), pc.created_at
        )
        UPDATE provider_configurations SET workspace_id = NULL
        WHERE id IN (SELECT id FROM admin_rows)
        """
    )


def downgrade() -> None:
    # Platform rows go back to the oldest platform admin's workspace.
    op.execute(
        """
        UPDATE provider_configurations SET workspace_id = (
            SELECT wm.workspace_id FROM workspace_members wm JOIN users u ON u.id = wm.user_id
            WHERE u.is_superuser ORDER BY wm.created_at LIMIT 1
        )
        WHERE workspace_id IS NULL
        """
    )
    op.execute("DELETE FROM provider_configurations WHERE workspace_id IS NULL")
    op.drop_index("uq_provider_configurations_platform_key", table_name="provider_configurations")
    op.alter_column("provider_configurations", "workspace_id", existing_type=sa.Uuid(), nullable=False)
