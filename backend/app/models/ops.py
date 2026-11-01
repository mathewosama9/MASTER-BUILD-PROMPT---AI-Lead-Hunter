import uuid

from sqlalchemy import Boolean, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, JSONType, Timestamps, UUIDPk


class SuppressionEntry(UUIDPk, Timestamps, Base):
    """Workspace-wide do-not-contact list, enforced across every campaign."""

    __tablename__ = "suppression_entries"
    __table_args__ = (UniqueConstraint("workspace_id", "kind", "value"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    value: Mapped[str] = mapped_column(String(500))
    reason: Mapped[str | None] = mapped_column(String(500))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class ProviderConfiguration(UUIDPk, Timestamps, Base):
    """Provider settings and encrypted credentials.

    `workspace_id IS NULL` is the platform-wide row, managed by platform admins only and used by every workspace.
    A workspace row (legacy, from before keys were centralised) still wins for that workspace when present.
    """

    __tablename__ = "provider_configurations"
    __table_args__ = (
        UniqueConstraint("workspace_id", "provider_key"),
        Index(
            "uq_provider_configurations_platform_key",
            "provider_key",
            unique=True,
            postgresql_where=text("workspace_id IS NULL"),
        ),
    )

    workspace_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    provider_key: Mapped[str] = mapped_column(String(40))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # Fernet-encrypted JSON of credentials. Never returned by the API.
    encrypted_credentials: Mapped[str | None] = mapped_column(Text)
    # rate_limit_per_minute, monthly_budget_usd, model, etc.
    settings: Mapped[dict] = mapped_column(JSONType, default=dict)
    last_status: Mapped[str | None] = mapped_column(String(32))
    last_error: Mapped[str | None] = mapped_column(Text)
    last_tested_at: Mapped[str | None] = mapped_column(String(40))


class ProviderUsage(UUIDPk, Timestamps, Base):
    __tablename__ = "provider_usage"
    __table_args__ = (Index("ix_provider_usage_ws_provider_created", "workspace_id", "provider_key", "created_at"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("campaigns.id", ondelete="SET NULL"), index=True)
    provider_key: Mapped[str] = mapped_column(String(40))
    operation: Mapped[str] = mapped_column(String(60))
    units: Mapped[int] = mapped_column(Integer, default=1)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    status_code: Mapped[int | None] = mapped_column(Integer)


class JobEvent(UUIDPk, Timestamps, Base):
    __tablename__ = "job_events"
    __table_args__ = (Index("ix_job_events_campaign_created", "campaign_id", "created_at"),)

    campaign_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"))
    run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("campaign_runs.id", ondelete="CASCADE"))
    stage: Mapped[str] = mapped_column(String(32))
    level: Mapped[str] = mapped_column(String(10), default="info")  # info | warning | error
    event_type: Mapped[str] = mapped_column(String(40))
    message: Mapped[str] = mapped_column(Text)
    provider_key: Mapped[str | None] = mapped_column(String(40))
    data: Mapped[dict] = mapped_column(JSONType, default=dict)


class AuditLog(UUIDPk, Timestamps, Base):
    __tablename__ = "audit_logs"

    workspace_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(80), index=True)
    entity_type: Mapped[str | None] = mapped_column(String(40))
    entity_id: Mapped[str | None] = mapped_column(String(64))
    data: Mapped[dict] = mapped_column(JSONType, default=dict)
    ip: Mapped[str | None] = mapped_column(String(64))
    via: Mapped[str] = mapped_column(String(16), default="web")
