import uuid
from datetime import datetime

from sqlalchemy import Boolean, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, JSONType, SoftDelete, Timestamps, UUIDPk, utcnow
from app.models.enums import CrmStatus, VerificationStatus


class Business(UUIDPk, Timestamps, SoftDelete, Base):
    """A real-world company. One row per workspace per company, shared across campaigns."""

    __tablename__ = "businesses"
    __table_args__ = (
        # Deduplicate by normalized domain inside a workspace (only when a domain is known).
        Index(
            "uq_businesses_ws_domain",
            "workspace_id",
            "normalized_domain",
            unique=True,
            postgresql_where=text("normalized_domain IS NOT NULL AND deleted_at IS NULL"),
            sqlite_where=text("normalized_domain IS NOT NULL AND deleted_at IS NULL"),
        ),
        Index("ix_businesses_ws_country_industry", "workspace_id", "country", "industry"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(300))
    normalized_name: Mapped[str] = mapped_column(String(300), index=True)
    website_url: Mapped[str | None] = mapped_column(String(500))
    normalized_domain: Mapped[str | None] = mapped_column(String(253))
    # Secondary identifiers used for deduplication when there is no domain (e.g. E.164 phone, registry id).
    identifiers: Mapped[dict] = mapped_column(JSONType, default=dict)
    industry: Mapped[str | None] = mapped_column(String(120))
    country: Mapped[str | None] = mapped_column(String(2))
    city: Mapped[str | None] = mapped_column(String(120))
    address: Mapped[str | None] = mapped_column(String(500))
    description: Mapped[str | None] = mapped_column(Text)
    company_size: Mapped[str | None] = mapped_column(String(32))
    language: Mapped[str | None] = mapped_column(String(8))
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_manual: Mapped[bool] = mapped_column(Boolean, default=False)
    crm_status: Mapped[str] = mapped_column(String(32), default=CrmStatus.NEW, index=True)
    latest_score: Mapped[float | None] = mapped_column(Float, index=True)
    latest_priority: Mapped[str | None] = mapped_column(String(16), index=True)
    recommended_service: Mapped[str | None] = mapped_column(String(120))
    has_verified_contact: Mapped[bool] = mapped_column(Boolean, default=False)
    contact_count: Mapped[int] = mapped_column(Integer, default=0)
    last_enriched_at: Mapped[datetime | None]
    last_analyzed_at: Mapped[datetime | None]

    contacts: Mapped[list["BusinessContact"]] = relationship(back_populates="business", lazy="raise")
    sources: Mapped[list["BusinessSource"]] = relationship(back_populates="business", lazy="raise")


class BusinessContact(UUIDPk, Timestamps, Base):
    __tablename__ = "business_contacts"
    __table_args__ = (UniqueConstraint("business_id", "type", "normalized_value"),)

    business_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), index=True)
    type: Mapped[str] = mapped_column(String(20))
    subtype: Mapped[str | None] = mapped_column(String(40))  # general | sales | support | facebook | ...
    value: Mapped[str] = mapped_column(String(500))
    normalized_value: Mapped[str] = mapped_column(String(500), index=True)
    person_name: Mapped[str | None] = mapped_column(String(200))
    person_role: Mapped[str | None] = mapped_column(String(200))
    source_url: Mapped[str | None] = mapped_column(String(1000))
    source_provider: Mapped[str] = mapped_column(String(40))
    retrieved_at: Mapped[datetime] = mapped_column(default=utcnow)
    verification_status: Mapped[str] = mapped_column(String(16), default=VerificationStatus.DISCOVERED)
    verified_at: Mapped[datetime | None]
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    usage_restrictions: Mapped[str | None] = mapped_column(String(500))
    is_suppressed: Mapped[bool] = mapped_column(Boolean, default=False)

    business: Mapped[Business] = relationship(back_populates="contacts")


class BusinessSource(UUIDPk, Timestamps, Base):
    __tablename__ = "business_sources"
    __table_args__ = (UniqueConstraint("business_id", "provider_key", "source_url"),)

    business_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), index=True)
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("campaigns.id", ondelete="SET NULL"))
    provider_key: Mapped[str] = mapped_column(String(40))
    source_url: Mapped[str] = mapped_column(String(1000))
    title: Mapped[str | None] = mapped_column(String(500))
    snippet: Mapped[str | None] = mapped_column(Text)
    raw: Mapped[dict] = mapped_column(JSONType, default=dict)
    discovered_at: Mapped[datetime] = mapped_column(default=utcnow)

    business: Mapped[Business] = relationship(back_populates="sources")


class BusinessEvidence(UUIDPk, Timestamps, Base):
    """A grounded observation captured from a source page. AI analysis may only cite these."""

    __tablename__ = "business_evidence"

    business_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(32))  # page | feature | channel
    signal_key: Mapped[str | None] = mapped_column(String(64))  # e.g. has_booking, has_contact_form
    url: Mapped[str | None] = mapped_column(String(1000))
    title: Mapped[str | None] = mapped_column(String(500))
    excerpt: Mapped[str | None] = mapped_column(Text)
    observed: Mapped[bool] = mapped_column(Boolean, default=True)
    captured_at: Mapped[datetime] = mapped_column(default=utcnow)


class LeadAssessment(UUIDPk, Timestamps, Base):
    __tablename__ = "lead_assessments"

    business_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), index=True)
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("campaigns.id", ondelete="SET NULL"))
    provider: Mapped[str] = mapped_column(String(32))  # anthropic | openai | demo | heuristic
    model: Mapped[str | None] = mapped_column(String(80))
    summary: Mapped[str] = mapped_column(Text, default="")
    observed_signals: Mapped[list] = mapped_column(JSONType, default=list)
    hypotheses: Mapped[list] = mapped_column(JSONType, default=list)
    potential_problems: Mapped[list] = mapped_column(JSONType, default=list)
    evidence_links: Mapped[list] = mapped_column(JSONType, default=list)
    recommended_services: Mapped[list] = mapped_column(JSONType, default=list)
    opportunity: Mapped[str] = mapped_column(Text, default="")
    suggested_pitch: Mapped[str] = mapped_column(Text, default="")
    unknowns: Mapped[list] = mapped_column(JSONType, default=list)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    industry_fit: Mapped[float] = mapped_column(Float, default=0.0)
    characteristics_fit: Mapped[float] = mapped_column(Float, default=0.0)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)


class LeadScore(UUIDPk, Timestamps, Base):
    __tablename__ = "lead_scores"

    business_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), index=True)
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("campaigns.id", ondelete="SET NULL"))
    assessment_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("lead_assessments.id", ondelete="SET NULL"))
    total: Mapped[float] = mapped_column(Float)
    priority: Mapped[str] = mapped_column(String(16))
    factors: Mapped[dict] = mapped_column(JSONType, default=dict)
    weights: Mapped[dict] = mapped_column(JSONType, default=dict)
    explanation: Mapped[list] = mapped_column(JSONType, default=list)
    scoring_version: Mapped[str] = mapped_column(String(16))


class LeadNote(UUIDPk, Timestamps, Base):
    __tablename__ = "lead_notes"

    business_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), index=True)
    author_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    body: Mapped[str] = mapped_column(Text)


class LeadTag(UUIDPk, Timestamps, Base):
    __tablename__ = "lead_tags"
    __table_args__ = (UniqueConstraint("business_id", "tag"),)

    business_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), index=True)
    tag: Mapped[str] = mapped_column(String(60), index=True)


class OutreachDraft(UUIDPk, Timestamps, Base):
    __tablename__ = "outreach_drafts"

    business_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), index=True)
    author_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    language: Mapped[str] = mapped_column(String(8))
    tone: Mapped[str] = mapped_column(String(32))
    length: Mapped[str] = mapped_column(String(16))
    service: Mapped[str | None] = mapped_column(String(120))
    short_intro: Mapped[str] = mapped_column(Text, default="")
    email_subject: Mapped[str] = mapped_column(String(300), default="")
    email_body: Mapped[str] = mapped_column(Text, default="")
    whatsapp_message: Mapped[str] = mapped_column(Text, default="")
    follow_up: Mapped[str] = mapped_column(Text, default="")
    proposal_summary: Mapped[str] = mapped_column(Text, default="")
    provider: Mapped[str] = mapped_column(String(32))
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)


class OutreachActivity(UUIDPk, Timestamps, Base):
    __tablename__ = "outreach_activities"

    business_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    type: Mapped[str] = mapped_column(String(40))  # status_change | note | draft_created | tag | edit
    payload: Mapped[dict] = mapped_column(JSONType, default=dict)
