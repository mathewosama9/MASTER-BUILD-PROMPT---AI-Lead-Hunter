import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, JSONType, SoftDelete, Timestamps, UUIDPk
from app.models.enums import CampaignStatus


class Campaign(UUIDPk, Timestamps, SoftDelete, Base):
    __tablename__ = "campaigns"
    __table_args__ = (Index("ix_campaigns_ws_status", "workspace_id", "status"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    name: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(32), default=CampaignStatus.DRAFT, index=True)
    stage: Mapped[str] = mapped_column(String(32), default="created")
    origin: Mapped[str] = mapped_column(String(16), default="web")  # web | telegram | api
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    # Geography
    country: Mapped[str] = mapped_column(String(2), index=True)
    city: Mapped[str | None] = mapped_column(String(120))
    region: Mapped[str | None] = mapped_column(String(120))
    language: Mapped[str] = mapped_column(String(8), default="en")

    # Targeting
    industry: Mapped[str] = mapped_column(String(120), index=True)
    keywords: Mapped[list] = mapped_column(JSONType, default=list)
    excluded_keywords: Mapped[list] = mapped_column(JSONType, default=list)
    company_size: Mapped[str | None] = mapped_column(String(32))
    characteristics: Mapped[list] = mapped_column(JSONType, default=list)
    services: Mapped[list] = mapped_column(JSONType, default=list)
    nl_query: Mapped[str | None] = mapped_column(Text)
    research_spec: Mapped[dict] = mapped_column(JSONType, default=dict)

    # Research settings: target_count, max_companies, max_pages_per_site, enrichment, ai_analysis,
    # email_verification, min_score, max_budget_usd, max_runtime_minutes, concurrency, exclude_duplicates
    settings: Mapped[dict] = mapped_column(JSONType, default=dict)

    # Live counters (authoritative counts are also derivable from campaign_leads).
    stats: Mapped[dict] = mapped_column(JSONType, default=dict)
    cost_discovery: Mapped[float] = mapped_column(Float, default=0.0)
    cost_ai: Mapped[float] = mapped_column(Float, default=0.0)
    last_error: Mapped[str | None] = mapped_column(Text)

    telegram_chat_id: Mapped[int | None] = mapped_column(BigInteger)
    telegram_status_message_id: Mapped[int | None] = mapped_column(BigInteger)

    started_at: Mapped[datetime | None]
    completed_at: Mapped[datetime | None]

    sources: Mapped[list["CampaignSource"]] = relationship(
        back_populates="campaign", lazy="selectin", cascade="all, delete-orphan"
    )


class CampaignSource(UUIDPk, Timestamps, Base):
    __tablename__ = "campaign_sources"
    __table_args__ = (UniqueConstraint("campaign_id", "provider_key"),)

    campaign_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), index=True)
    provider_key: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(24), default="pending")  # pending|running|done|failed|skipped
    results_count: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    # Manual URLs for providers without programmatic discovery (e.g. Facebook pages).
    manual_urls: Mapped[list] = mapped_column(JSONType, default=list)

    campaign: Mapped[Campaign] = relationship(back_populates="sources")


class CampaignRun(UUIDPk, Timestamps, Base):
    __tablename__ = "campaign_runs"
    __table_args__ = (UniqueConstraint("campaign_id", "run_number"),)

    campaign_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), index=True)
    run_number: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), default=CampaignStatus.QUEUED)
    stage: Mapped[str] = mapped_column(String(32), default="created")
    # Resume checkpoint: completed stages, processed business ids, provider cursors.
    checkpoint: Mapped[dict] = mapped_column(JSONType, default=dict)
    counters: Mapped[dict] = mapped_column(JSONType, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    celery_task_id: Mapped[str | None] = mapped_column(String(64))
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]


class CampaignLead(UUIDPk, Timestamps, Base):
    __tablename__ = "campaign_leads"
    __table_args__ = (UniqueConstraint("campaign_id", "business_id"),)

    campaign_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), index=True)
    business_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), index=True)
    run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("campaign_runs.id", ondelete="SET NULL"))
    discovered_via: Mapped[str] = mapped_column(String(40))
    # Was this business already known to the workspace before this campaign?
    pre_existing: Mapped[bool] = mapped_column(Boolean, default=False)
    enriched: Mapped[bool] = mapped_column(Boolean, default=False)
    analyzed: Mapped[bool] = mapped_column(Boolean, default=False)
    scored: Mapped[bool] = mapped_column(Boolean, default=False)
    score: Mapped[float | None] = mapped_column(Float, index=True)
    priority: Mapped[str | None] = mapped_column(String(16))
    qualified: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    processing_error: Mapped[str | None] = mapped_column(Text)
