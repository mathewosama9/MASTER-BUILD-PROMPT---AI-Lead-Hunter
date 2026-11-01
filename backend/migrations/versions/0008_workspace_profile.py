"""workspace profile: what the workspace sells and its ideal customer

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-31 18:00:00.000000
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The fixed service list the product shipped with. Workspaces that already ran campaigns keep these as their own
# offerings (same ids), so existing campaigns, assessments and exports still resolve.
LEGACY_OFFERINGS = [
    ("ai_support_agent", "AI Customer Support Agent"),
    ("whatsapp_automation", "WhatsApp Automation"),
    ("n8n_automation", "n8n Workflow Automation"),
    ("crm_integration", "CRM Integration"),
    ("appointment_automation", "Appointment Scheduling Automation"),
    ("website_development", "Website Development"),
    ("ecommerce_development", "E-commerce Development"),
    ("lead_management", "Lead Management Automation"),
    ("ai_sales_assistant", "AI Sales Assistant"),
    ("process_automation", "Business Process Automation"),
]


def upgrade() -> None:
    jsonb = postgresql.JSONB(astext_type=sa.Text())
    op.create_table(
        "workspace_profiles",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("company_name", sa.String(length=200), server_default="", nullable=False),
        sa.Column("website", sa.String(length=500), nullable=True),
        sa.Column("business_category", sa.String(length=60), nullable=True),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.Column("value_proposition", sa.Text(), server_default="", nullable=False),
        sa.Column("offerings", jsonb, server_default="[]", nullable=False),
        sa.Column("target_industries", jsonb, server_default="[]", nullable=False),
        sa.Column("target_countries", jsonb, server_default="[]", nullable=False),
        sa.Column("target_cities", jsonb, server_default="[]", nullable=False),
        sa.Column("company_sizes", jsonb, server_default="[]", nullable=False),
        sa.Column("good_signals", jsonb, server_default="[]", nullable=False),
        sa.Column("disqualifiers", jsonb, server_default="[]", nullable=False),
        sa.Column("sender_name", sa.String(length=120), server_default="", nullable=False),
        sa.Column("outreach_language", sa.String(length=8), server_default="ar", nullable=False),
        sa.Column("tone", sa.String(length=32), server_default="professional", nullable=False),
        sa.Column("channels", jsonb, server_default="[]", nullable=False),
        sa.Column("onboarding_step", sa.Integer(), server_default="0", nullable=False),
        sa.Column("onboarding_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_workspace_profiles_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workspace_profiles")),
    )
    op.create_index(op.f("ix_workspace_profiles_workspace_id"), "workspace_profiles", ["workspace_id"], unique=True)

    # Workspaces that already ran campaigns are past onboarding: give them the legacy offerings and carry over
    # the sender name / default services they may have saved in settings. Others go through onboarding.
    offerings = json.dumps([{"id": k, "name": name, "description": "", "keywords": []} for k, name in LEGACY_OFFERINGS])
    op.execute(
        sa.text(
            """
            INSERT INTO workspace_profiles (id, workspace_id, company_name, offerings, sender_name,
                                            onboarding_step, onboarding_completed_at)
            SELECT gen_random_uuid(), w.id, w.name, CAST(:offerings AS jsonb),
                   COALESCE(w.settings->>'sender_name', ''), 6, now()
            FROM workspaces w
            WHERE w.deleted_at IS NULL AND EXISTS (SELECT 1 FROM campaigns c WHERE c.workspace_id = w.id)
            """
        ).bindparams(offerings=offerings)
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_workspace_profiles_workspace_id"), table_name="workspace_profiles")
    op.drop_table("workspace_profiles")
