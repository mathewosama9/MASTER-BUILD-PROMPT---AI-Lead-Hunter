"""Common contract for every discovery source.

Adding a new source = implement `DiscoveryProvider` and register it in `registry.py`.
The pipeline only depends on this module.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field

from app.models.enums import ProviderStatus


class SearchQuery(BaseModel):
    country: str
    city: str | None = None
    region: str | None = None
    language: str = "en"
    industry: str
    keywords: list[str] = Field(default_factory=list)
    excluded_keywords: list[str] = Field(default_factory=list)
    company_size: str | None = None
    limit: int = 20
    manual_urls: list[str] = Field(default_factory=list)


class BusinessCandidate(BaseModel):
    """Normalized discovery result. Only facts the source actually returned."""

    name: str
    website_url: str | None = None
    industry: str | None = None
    country: str | None = None
    city: str | None = None
    address: str | None = None
    description: str | None = None
    phone: str | None = None
    email: str | None = None
    source_provider: str
    source_url: str
    source_title: str | None = None
    discovered_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    raw: dict = Field(default_factory=dict)
    # Stable ids from the source listing, used for dedup when there is no domain/phone: {"osm": "node/1"}.
    identifiers: dict[str, str] = Field(default_factory=dict)
    # Social profile URLs published by the source listing (Maps, OSM tags, imported rows).
    social_urls: list[str] = Field(default_factory=list)
    is_demo: bool = False


@dataclass
class ProviderInfo:
    key: str
    name: str
    kind: str  # discovery | enrichment | ai
    description: str
    requires: list[str] = field(default_factory=list)
    docs_url: str | None = None


@dataclass
class ProviderState:
    status: ProviderStatus
    detail: str | None = None


class ProviderError(Exception):
    """A provider call failed. `retryable` tells the pipeline whether backoff makes sense."""

    def __init__(self, message: str, *, retryable: bool = False, status_code: int | None = None) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.status_code = status_code


class ProviderUnavailable(ProviderError):
    pass


class RateLimited(ProviderError):
    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message, retryable=True, status_code=429)
        self.retry_after = retry_after


UsageRecorder = Callable[[str, str, int, float, bool, int | None], Awaitable[None]]
"""(provider_key, operation, units, cost_usd, success, status_code) -> None"""


async def _noop_usage(*_: object) -> None:
    return None


@dataclass
class ProviderContext:
    credentials: dict[str, str]
    settings: dict
    record_usage: UsageRecorder = _noop_usage
    campaign_id: str | None = None


@runtime_checkable
class DiscoveryProvider(Protocol):
    info: ProviderInfo

    def state(self, ctx: ProviderContext) -> ProviderState: ...

    async def search_businesses(self, query: SearchQuery, ctx: ProviderContext) -> list[BusinessCandidate]: ...

    async def test_connection(self, ctx: ProviderContext) -> ProviderState: ...
