import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl

from app.models.enums import CrmStatus, SuppressionKind, VerificationStatus
from app.schemas.common import ORM


class LeadRow(BaseModel):
    id: uuid.UUID
    name: str
    website_url: str | None
    normalized_domain: str | None
    country: str | None
    city: str | None
    industry: str | None
    latest_score: float | None
    latest_priority: str | None
    recommended_service: str | None
    crm_status: str
    contact_count: int
    has_verified_contact: bool
    is_demo: bool
    sources: list[str]
    campaigns: list[dict]
    tags: list[str]
    outreach_eligible: bool
    updated_at: datetime


class ContactOut(ORM):
    id: uuid.UUID
    type: str
    subtype: str | None
    value: str
    person_name: str | None
    person_role: str | None
    source_url: str | None
    source_provider: str
    retrieved_at: datetime
    verification_status: str
    verified_at: datetime | None
    confidence: float
    usage_restrictions: str | None
    is_suppressed: bool


class SourceOut(ORM):
    id: uuid.UUID
    provider_key: str
    source_url: str
    title: str | None
    snippet: str | None
    discovered_at: datetime
    campaign_id: uuid.UUID | None


class EvidenceOut(ORM):
    id: uuid.UUID
    kind: str
    signal_key: str | None
    url: str | None
    title: str | None
    excerpt: str | None
    observed: bool
    captured_at: datetime


class AssessmentOut(ORM):
    id: uuid.UUID
    campaign_id: uuid.UUID | None
    provider: str
    model: str | None
    summary: str
    observed_signals: list
    hypotheses: list
    potential_problems: list
    evidence_links: list
    recommended_services: list
    opportunity: str
    suggested_pitch: str
    unknowns: list
    confidence: float
    industry_fit: float
    characteristics_fit: float
    cost_usd: float
    created_at: datetime


class ScoreOut(ORM):
    id: uuid.UUID
    campaign_id: uuid.UUID | None
    total: float
    priority: str
    factors: dict
    weights: dict
    explanation: list
    scoring_version: str
    created_at: datetime


class NoteOut(ORM):
    id: uuid.UUID
    body: str
    author_id: uuid.UUID | None
    created_at: datetime


class ActivityOut(ORM):
    id: uuid.UUID
    type: str
    payload: dict
    user_id: uuid.UUID | None
    created_at: datetime


class DraftOut(ORM):
    id: uuid.UUID
    language: str
    tone: str
    length: str
    service: str | None
    short_intro: str
    email_subject: str
    email_body: str
    whatsapp_message: str
    follow_up: str
    proposal_summary: str
    provider: str
    created_at: datetime


class LeadDetail(BaseModel):
    business: dict
    contacts: list[ContactOut]
    sources: list[SourceOut]
    evidence: list[EvidenceOut]
    assessment: AssessmentOut | None
    assessments: list[AssessmentOut]
    score: ScoreOut | None
    campaigns: list[dict]
    notes: list[NoteOut]
    tags: list[str]
    activities: list[ActivityOut]
    drafts: list[DraftOut]
    outreach_eligible: bool
    suppressed: bool


class LeadUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=300)
    website_url: str | None = Field(default=None, max_length=500)
    industry: str | None = Field(default=None, max_length=120)
    city: str | None = Field(default=None, max_length=120)
    country: str | None = Field(default=None, max_length=2)
    address: str | None = Field(default=None, max_length=500)
    description: str | None = Field(default=None, max_length=4000)
    crm_status: CrmStatus | None = None


class LeadCreate(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    website_url: HttpUrl | None = None
    industry: str | None = Field(default=None, max_length=120)
    country: str | None = Field(default=None, max_length=2)
    city: str | None = Field(default=None, max_length=120)
    description: str | None = Field(default=None, max_length=4000)
    phone: str | None = Field(default=None, max_length=40)
    email: str | None = Field(default=None, max_length=320)
    source_url: HttpUrl | None = None


class BulkAction(BaseModel):
    ids: list[uuid.UUID] = Field(min_length=1, max_length=1000)
    action: Literal["set_status", "add_tag", "remove_tag", "suppress", "delete"]
    value: str | None = Field(default=None, max_length=60)


class NoteIn(BaseModel):
    body: str = Field(min_length=1, max_length=5000)


class TagIn(BaseModel):
    tag: str = Field(min_length=1, max_length=60)


class ContactUpdate(BaseModel):
    verification_status: VerificationStatus | None = None
    is_suppressed: bool | None = None


class PitchIn(BaseModel):
    language: Literal["en", "ar"] = "en"
    tone: Literal["professional", "friendly", "concise", "consultative"] = "professional"
    length: Literal["short", "medium", "long"] = "short"
    service: str | None = None


class SuppressionIn(BaseModel):
    kind: SuppressionKind
    value: str = Field(min_length=1, max_length=500)
    reason: str | None = Field(default=None, max_length=500)


class SuppressionOut(ORM):
    id: uuid.UUID
    kind: str
    value: str
    reason: str | None
    created_at: datetime
