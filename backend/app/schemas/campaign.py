import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.schemas.common import ORM


class ResearchSettings(BaseModel):
    target_count: int = Field(default=20, ge=1, le=500)
    max_companies: int = Field(default=40, ge=1, le=1000)
    max_pages_per_site: int = Field(default=5, ge=1, le=15)
    enrichment: bool = True
    ai_analysis: bool = True
    email_verification: bool = False
    min_score: float = Field(default=50, ge=0, le=100)
    max_budget_usd: float = Field(default=5.0, ge=0, le=1000)
    max_runtime_minutes: int = Field(default=30, ge=1, le=600)
    concurrency: int = Field(default=4, ge=1, le=10)
    exclude_duplicates: bool = False

    @field_validator("max_companies")
    @classmethod
    def _at_least_target(cls, v: int, info) -> int:  # noqa: ANN001
        target = info.data.get("target_count", 1)
        return max(v, target)


class SourceIn(BaseModel):
    provider_key: str = Field(min_length=1, max_length=40)
    # URLs for manual/facebook sources; JSON-encoded rows (services/imports.py) for the import source.
    manual_urls: list[str] = Field(default_factory=list, max_length=1000)


class CampaignCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    country: str = Field(min_length=2, max_length=2)
    city: str | None = Field(default=None, max_length=120)
    region: str | None = Field(default=None, max_length=120)
    language: Literal["en", "ar"] = "en"
    industry: str = Field(min_length=1, max_length=120)
    keywords: list[str] = Field(default_factory=list, max_length=30)
    excluded_keywords: list[str] = Field(default_factory=list, max_length=30)
    company_size: str | None = Field(default=None, max_length=32)
    characteristics: list[str] = Field(default_factory=list, max_length=20)
    services: list[str] = Field(default_factory=list, max_length=10)
    nl_query: str | None = Field(default=None, max_length=2000)
    research_spec: dict = Field(default_factory=dict)
    sources: list[SourceIn] = Field(min_length=1, max_length=10)
    settings: ResearchSettings = Field(default_factory=ResearchSettings)
    is_demo: bool | None = None
    start: bool = False

    @field_validator("country")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.upper()

    @field_validator("keywords", "excluded_keywords", "characteristics")
    @classmethod
    def _clean(cls, v: list[str]) -> list[str]:
        return [s.strip()[:100] for s in v if s and s.strip()]


class CampaignUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    city: str | None = None
    region: str | None = None
    keywords: list[str] | None = None
    excluded_keywords: list[str] | None = None
    characteristics: list[str] | None = None
    services: list[str] | None = None
    sources: list[SourceIn] | None = None
    settings: ResearchSettings | None = None


class SourceOut(ORM):
    provider_key: str
    status: str
    results_count: int
    last_error: str | None
    manual_urls: list[str]


class CampaignOut(ORM):
    id: uuid.UUID
    name: str
    status: str
    stage: str
    origin: str
    is_demo: bool
    country: str
    city: str | None
    region: str | None
    language: str
    industry: str
    keywords: list[str]
    excluded_keywords: list[str]
    company_size: str | None
    characteristics: list[str]
    services: list[str]
    nl_query: str | None
    settings: dict
    stats: dict
    cost_discovery: float
    cost_ai: float
    last_error: str | None
    sources: list[SourceOut]
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class RunOut(ORM):
    id: uuid.UUID
    run_number: int
    status: str
    stage: str
    counters: dict
    error: str | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime


class EventOut(ORM):
    id: uuid.UUID
    stage: str
    level: str
    event_type: str
    message: str
    provider_key: str | None
    data: dict
    created_at: datetime


class ParseSpecIn(BaseModel):
    text: str = Field(min_length=3, max_length=2000)


class EstimateOut(BaseModel):
    providers: dict[str, dict]
    estimated_requests: int
    estimated_cost_usd: float | None
    notes: list[str]


class ImportPreviewIn(BaseModel):
    filename: str = Field(min_length=1, max_length=200)
    content_base64: str = Field(min_length=1, max_length=8_000_000)


class ImportPreviewOut(BaseModel):
    rows: list[dict]
    rejected: list[dict]
    encoded: list[str]
