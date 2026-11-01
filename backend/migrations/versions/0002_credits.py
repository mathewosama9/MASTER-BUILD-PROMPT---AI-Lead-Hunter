"""credits: platform settings, packages, ledger, top-ups

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-30 09:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    ]


def upgrade() -> None:
    op.add_column("workspaces", sa.Column("credit_balance", sa.Integer(), server_default="0", nullable=False))
    op.add_column("workspaces", sa.Column("trial_ends_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("workspaces", sa.Column("billing_exempt", sa.Boolean(), server_default="false", nullable=False))
    op.create_check_constraint("credit_balance_non_negative", "workspaces", "credit_balance >= 0")
    # Every workspace that exists before self-signup is the platform operator's own: keep it unmetered.
    op.execute("UPDATE workspaces SET billing_exempt = true")

    op.add_column("campaign_leads", sa.Column("credits_charged", sa.Integer(), server_default="0", nullable=False))

    op.create_table(
        "platform_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("trial_days", sa.Integer(), nullable=False),
        sa.Column("trial_credits", sa.Integer(), nullable=False),
        sa.Column("credits_per_contact", sa.Integer(), nullable=False),
        sa.Column("payment_instructions_ar", sa.Text(), nullable=False),
        sa.Column("payment_instructions_en", sa.Text(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint("id = 1", name=op.f("ck_platform_settings_single_row")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_platform_settings")),
    )
    op.execute(
        "INSERT INTO platform_settings (id, trial_days, trial_credits, credits_per_contact, "
        "payment_instructions_ar, payment_instructions_en) VALUES (1, 30, 100, 1, '', '')"
    )

    op.create_table(
        "credit_packages",
        sa.Column("name_ar", sa.String(length=120), nullable=False),
        sa.Column("name_en", sa.String(length=120), nullable=False),
        sa.Column("credits", sa.Integer(), nullable=False),
        sa.Column("price", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("sort", sa.Integer(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_credit_packages")),
    )

    op.create_table(
        "credit_transactions",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("delta", sa.Integer(), nullable=False),
        sa.Column("balance_after", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("campaign_id", sa.Uuid(), nullable=True),
        sa.Column("business_id", sa.Uuid(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["business_id"],
            ["businesses.id"],
            name=op.f("fk_credit_transactions_business_id_businesses"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["campaign_id"],
            ["campaigns.id"],
            name=op.f("fk_credit_transactions_campaign_id_campaigns"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_credit_transactions_created_by_users"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_credit_transactions_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_credit_transactions")),
    )
    op.create_index("ix_credit_transactions_ws_created", "credit_transactions", ["workspace_id", "created_at"])

    op.create_table(
        "topup_requests",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("package_id", sa.Uuid(), nullable=True),
        sa.Column("credits", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("method", sa.String(length=20), nullable=False),
        sa.Column("reference", sa.String(length=200), nullable=True),
        sa.Column("receipt_path", sa.String(length=500), nullable=True),
        sa.Column("receipt_content_type", sa.String(length=100), nullable=True),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("reviewed_by", sa.Uuid(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("transaction_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_topup_requests_created_by_users"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["package_id"],
            ["credit_packages.id"],
            name=op.f("fk_topup_requests_package_id_credit_packages"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by"], ["users.id"], name=op.f("fk_topup_requests_reviewed_by_users"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["transaction_id"],
            ["credit_transactions.id"],
            name=op.f("fk_topup_requests_transaction_id_credit_transactions"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_topup_requests_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_topup_requests")),
    )
    op.create_index(op.f("ix_topup_requests_status"), "topup_requests", ["status"])
    op.create_index(op.f("ix_topup_requests_workspace_id"), "topup_requests", ["workspace_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_topup_requests_workspace_id"), table_name="topup_requests")
    op.drop_index(op.f("ix_topup_requests_status"), table_name="topup_requests")
    op.drop_table("topup_requests")
    op.drop_index("ix_credit_transactions_ws_created", table_name="credit_transactions")
    op.drop_table("credit_transactions")
    op.drop_table("credit_packages")
    op.drop_table("platform_settings")
    op.drop_column("campaign_leads", "credits_charged")
    op.drop_constraint("credit_balance_non_negative", "workspaces", type_="check")
    op.drop_column("workspaces", "billing_exempt")
    op.drop_column("workspaces", "trial_ends_at")
    op.drop_column("workspaces", "credit_balance")
