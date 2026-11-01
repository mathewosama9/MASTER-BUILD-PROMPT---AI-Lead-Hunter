"""The workspace's own business: what it sells (offerings) and who it sells to (ideal customer profile)."""

from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.api.deps import DB, CurrentPrincipal, audit, require_role
from app.core.errors import AppError
from app.models import Workspace
from app.models.enums import ProviderStatus, Role
from app.research.catalog import INDUSTRIES, PROVIDER_CATEGORIES
from app.schemas.campaign import CampaignCreate, CampaignOut, ResearchSettings, SourceIn
from app.services import campaigns as campaign_svc
from app.services import credits as credit_svc
from app.services import providers as provider_svc
from app.services.profile import ONBOARDING_STEPS, clean_offerings, get_profile, onboarding_state

router = APIRouter(tags=["profile"])


class OfferingIn(BaseModel):
    id: str | None = Field(default=None, max_length=40)
    name: str = Field(max_length=120)
    description: str = Field(default="", max_length=600)
    keywords: list[str] = Field(default_factory=list, max_length=15)


class ProfileIn(BaseModel):
    company_name: str | None = Field(default=None, max_length=200)
    website: str | None = Field(default=None, max_length=500)
    business_category: str | None = Field(default=None, max_length=60)
    description: str | None = Field(default=None, max_length=4000)
    value_proposition: str | None = Field(default=None, max_length=2000)
    offerings: list[OfferingIn] | None = Field(default=None, max_length=12)
    target_industries: list[str] | None = Field(default=None, max_length=30)
    target_countries: list[str] | None = Field(default=None, max_length=30)
    target_cities: list[str] | None = Field(default=None, max_length=50)
    company_sizes: list[str] | None = Field(default=None, max_length=10)
    good_signals: list[str] | None = Field(default=None, max_length=20)
    disqualifiers: list[str] | None = Field(default=None, max_length=20)
    sender_name: str | None = Field(default=None, max_length=120)
    outreach_language: Literal["ar", "en"] | None = None
    tone: Literal["professional", "friendly", "concise", "consultative"] | None = None
    channels: list[Literal["whatsapp", "email", "phone", "linkedin"]] | None = None
    onboarding_step: int | None = Field(default=None, ge=0, le=ONBOARDING_STEPS)
    # True when the user finishes or skips the onboarding wizard.
    onboarding_completed: bool | None = None


LIST_FIELDS = (
    "target_industries",
    "target_countries",
    "target_cities",
    "company_sizes",
    "good_signals",
    "disqualifiers",
    "channels",
)


def profile_out(p) -> dict:  # noqa: ANN001
    return {
        "company_name": p.company_name,
        "website": p.website,
        "business_category": p.business_category,
        "description": p.description,
        "value_proposition": p.value_proposition,
        "offerings": p.offerings or [],
        **{f: getattr(p, f) or [] for f in LIST_FIELDS},
        "sender_name": p.sender_name,
        "outreach_language": p.outreach_language,
        "tone": p.tone,
        "onboarding": onboarding_state(p),
    }


@router.get("/profile")
async def read_profile(p: CurrentPrincipal, db: DB) -> dict:
    profile = await get_profile(db, p.workspace_id)
    await db.commit()  # persist the empty profile created on first read
    return profile_out(profile)


@router.put("/profile", dependencies=[require_role(Role.ADMIN)])
async def update_profile(body: ProfileIn, p: CurrentPrincipal, db: DB) -> dict:
    profile = await get_profile(db, p.workspace_id)
    data = body.model_dump(exclude_none=True)
    if "offerings" in data:
        profile.offerings = clean_offerings(data.pop("offerings"))
    if "onboarding_step" in data:
        profile.onboarding_step = max(profile.onboarding_step or 0, data.pop("onboarding_step"))
    if data.pop("onboarding_completed", None) and profile.onboarding_completed_at is None:
        profile.onboarding_completed_at = datetime.now(UTC)
    if "business_category" in data and data["business_category"] not in PROVIDER_CATEGORIES:
        data["business_category"] = "other"
    for field in LIST_FIELDS:
        if field in data:
            seen: dict[str, str] = {}
            for v in data.pop(field):
                v = str(v).strip()[:120]
                if v and v.casefold() not in seen:
                    seen[v.casefold()] = v
            setattr(profile, field, list(seen.values()))
    for field, value in data.items():
        setattr(profile, field, value.strip() if isinstance(value, str) else value)
    await audit(db, p, "profile.updated", "workspace", p.workspace_id, {"fields": sorted(body.model_fields_set)})
    await db.commit()
    return profile_out(profile)


# Sources the first search may use, in order; only the ones connected right now are kept.
FIRST_SEARCH_SOURCES = ("google_maps", "osm", "directories", "social_discovery", "brave")
FIRST_SEARCH_SETTINGS = ResearchSettings(target_count=15, max_companies=30)


@router.post("/profile/first-search", response_model=CampaignOut, status_code=201, dependencies=[require_role(Role.ADMIN)])
async def first_search(p: CurrentPrincipal, db: DB, request: Request) -> CampaignOut:
    """Onboarding's last step: a small campaign built from the profile and started at once, so a new user sees
    real leads within minutes instead of filling the full campaign wizard first."""
    profile = await get_profile(db, p.workspace_id)
    industry = next(iter(profile.target_industries or []), None)
    country = next(iter(profile.target_countries or []), None)
    if not industry or not country:
        raise AppError("Choose who you sell to and in which country first", code="profile_incomplete")
    # Fail before creating anything when the trial can't pay for it yet (e.g. email not confirmed).
    await credit_svc.ensure_can_spend(db, await db.get(Workspace, p.workspace_id))
    sources = [
        SourceIn(provider_key=k)
        for k in FIRST_SEARCH_SOURCES
        if (await provider_svc.provider_state(db, p.workspace_id, k)).status == ProviderStatus.CONNECTED
    ]
    if not sources:
        raise AppError("Search is not available right now. Please try again later.", code="no_sources", status_code=503)
    city = next(iter(profile.target_cities or []), None)
    lang = "ar" if profile.outreach_language == "ar" else "en"
    label = INDUSTRIES.get(industry, {}).get(lang) or industry
    data = CampaignCreate(
        name=" · ".join(x for x in (label, city) if x),
        country=country,
        city=city,
        language=lang,
        industry=industry,
        services=[o["id"] for o in (profile.offerings or []) if o.get("id")][:10],
        sources=sources,
        settings=FIRST_SEARCH_SETTINGS,
        start=True,
    )
    chat_id = p.telegram_account.chat_id if p.telegram_account else None
    campaign = await campaign_svc.create_campaign(db, p.workspace_id, p.user.id, data, origin=p.via, telegram_chat_id=chat_id)
    profile.onboarding_step = ONBOARDING_STEPS
    profile.onboarding_completed_at = profile.onboarding_completed_at or datetime.now(UTC)
    await audit(
        db,
        p,
        "campaign.created",
        "campaign",
        campaign.id,
        {"name": campaign.name, "onboarding": True},
        request.client.host if request.client else None,
    )
    await db.commit()
    await campaign_svc.start_campaign(db, campaign)
    await db.refresh(campaign)
    return CampaignOut.model_validate(campaign)
