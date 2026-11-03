"""Unauthenticated endpoints for the public site: trial terms, credit packages and the contact form."""

import logging
import re
import uuid

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import func, or_, select

from app.api.deps import DB
from app.api.v1.billing import active_packages
from app.core.config import get_settings
from app.core.ratelimit import enforce
from app.models import Business, BusinessContact, Campaign, CampaignLead, ContactRequest, LeadAssessment, Testimonial
from app.models.enums import ContactInterest, ContactType, TestimonialStatus
from app.research.catalog import PROVIDER_CATEGORIES
from app.schemas.billing import PackageOut
from app.schemas.marketing import PublicTestimonialOut
from app.services import credits as credit_svc
from app.services.notify import notify_admins

log = logging.getLogger(__name__)
router = APIRouter(prefix="/public", tags=["public"])


@router.get("/trial")
async def trial(db: DB) -> dict:
    s = await credit_svc.platform_settings(db)
    await db.commit()  # persists the default row the first time
    return {"trial_days": s.trial_days, "trial_credits": s.trial_credits, "credits_per_contact": s.credits_per_contact}


@router.get("/packages", response_model=list[PackageOut])
async def packages(db: DB) -> list[PackageOut]:
    return [PackageOut.model_validate(x) for x in await active_packages(db)]


@router.get("/testimonials", response_model=list[PublicTestimonialOut])
async def testimonials(db: DB) -> list[PublicTestimonialOut]:
    rows = await db.scalars(
        select(Testimonial)
        .where(Testimonial.status == TestimonialStatus.APPROVED)
        .order_by(Testimonial.is_featured.desc(), Testimonial.sort, Testimonial.created_at.desc())
        .limit(12)
    )
    return [PublicTestimonialOut.model_validate(t) for t in rows]


class ContactIn(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    company: str | None = Field(default=None, max_length=200)
    email: EmailStr
    phone: str | None = Field(default=None, max_length=32)
    interest: ContactInterest = ContactInterest.DEMO
    message: str = Field(default="", max_length=3000)
    locale: str = Field(default="ar", pattern="^(ar|en)$")
    # Honeypot: real visitors never see or fill this field.
    website: str | None = Field(default=None, max_length=200)

    @field_validator("name", "company", "phone", "message")
    @classmethod
    def _strip(cls, v: str | None) -> str | None:
        return v.strip() if isinstance(v, str) else v


@router.post("/contact", status_code=201)
async def contact(body: ContactIn, request: Request, db: DB) -> dict:
    ip = request.client.host if request.client else "unknown"
    await enforce(f"contact:{ip}", get_settings().contact_limit_per_hour, 3600)
    if body.website:  # a bot filled the hidden field: pretend success, store nothing
        return {"status": "received"}
    c = ContactRequest(
        name=body.name,
        company=body.company or None,
        email=body.email.lower(),
        phone=body.phone or None,
        interest=body.interest,
        message=body.message,
        locale=body.locale,
        ip=ip,
    )
    db.add(c)
    await notify_admins(
        db,
        "admin_contact",
        {
            "name": c.name,
            "company": c.company,
            "email": c.email,
            "phone": c.phone,
            "interest": c.interest,
            "message": (c.message or "")[:1500],
        },
        link="/app/admin?tab=contacts",
    )
    await db.commit()
    return {"status": "received"}


# ---------------------------------------------------------------- live preview
#
# Real results from searches the platform ran in its own showcase workspace (PlatformSettings.showcase_workspace_id).
# Customer workspaces are never read. Names are partly hidden and contact values never leave the server.

PREVIEW_CONTACT_TYPES = (ContactType.PHONE, ContactType.WHATSAPP, ContactType.EMAIL, ContactType.PERSON)


def mask_name(name: str) -> str:
    """Keep the first word (or first two letters of a one-word name) and hide the rest."""
    words = name.split()
    if len(words) > 1:
        return " ".join([words[0], *("•" * min(len(w), 6) for w in words[1:])])
    return name[:2] + "•" * min(max(len(name) - 2, 3), 6)


def _first_sentence(text: str) -> str:
    return re.split(r"(?<=[.!؟?])\s", text.strip(), maxsplit=1)[0][:220]


async def _showcase_id(db) -> uuid.UUID | None:  # noqa: ANN001
    return (await credit_svc.platform_settings(db)).showcase_workspace_id


async def _limit(request: Request) -> None:
    ip = request.client.host if request.client else "unknown"
    await enforce(f"preview:{ip}", get_settings().preview_limit_per_hour, 3600)


def _searches(ws: uuid.UUID):  # noqa: ANN202
    """Business ids delivered with a contact by the showcase workspace's real searches, with where they were run."""
    return (
        select(Campaign.industry, Campaign.country, Campaign.city, CampaignLead.business_id, Campaign.completed_at)
        .join(CampaignLead, CampaignLead.campaign_id == Campaign.id)
        .join(Business, Business.id == CampaignLead.business_id)
        .where(
            Campaign.workspace_id == ws,
            Campaign.deleted_at.is_(None),
            Campaign.is_demo.is_(False),
            Business.deleted_at.is_(None),
            Business.contact_count > 0,
        )
    )


@router.get("/preview/options")
async def preview_options(request: Request, db: DB) -> dict:
    """Which "I sell…" categories and places have real preview data."""
    await _limit(request)
    ws = await _showcase_id(db)
    if ws is None:
        return {"categories": []}
    sub = _searches(ws).subquery()
    rows = (
        await db.execute(
            select(sub.c.industry, sub.c.country, sub.c.city, func.count(func.distinct(sub.c.business_id))).group_by(
                sub.c.industry, sub.c.country, sub.c.city
            )
        )
    ).all()
    out = []
    for key, cat in PROVIDER_CATEGORIES.items():
        places: dict[tuple[str, str | None], int] = {}
        for industry, country, city, n in rows:
            if industry in cat["targets"]:
                places[(country, city)] = places.get((country, city), 0) + int(n)
        if places:
            out.append(
                {
                    "key": key,
                    "en": cat["en"],
                    "ar": cat["ar"],
                    "places": [
                        {"country": c, "city": city, "count": n}
                        for (c, city), n in sorted(places.items(), key=lambda x: -x[1])
                    ],
                }
            )
    return {"categories": out}


@router.get("/preview")
async def preview(
    request: Request,
    db: DB,
    category: str = Query(max_length=60),
    country: str = Query(min_length=2, max_length=2),
    city: str | None = Query(None, max_length=120),
) -> dict:
    """How many reachable businesses a real search found for this kind of seller and place, plus three of them."""
    await _limit(request)
    ws = await _showcase_id(db)
    cat = PROVIDER_CATEGORIES.get(category)
    empty = {"count": 0, "searched_at": None, "samples": []}
    if ws is None or cat is None:
        return empty
    q = _searches(ws).where(Campaign.industry.in_(cat["targets"]), Campaign.country == country.upper())
    q = q.where(Campaign.city == city) if city else q
    sub = q.subquery()
    count, searched_at = (
        await db.execute(select(func.count(func.distinct(sub.c.business_id)), func.max(sub.c.completed_at)))
    ).one()
    if not count:
        return empty
    top = list(
        await db.scalars(
            select(Business)
            .where(Business.id.in_(select(sub.c.business_id)))
            .order_by(Business.latest_score.desc().nulls_last())
            .limit(3)
        )
    )
    ids = [b.id for b in top]
    kinds: dict[uuid.UUID, set[str]] = {i: set() for i in ids}
    for bid, kind in await db.execute(
        select(BusinessContact.business_id, BusinessContact.type).where(
            BusinessContact.business_id.in_(ids),
            BusinessContact.type.in_(PREVIEW_CONTACT_TYPES),
            BusinessContact.is_suppressed.is_(False),
            # a decision maker counts only once verified
            or_(BusinessContact.type != ContactType.PERSON, BusinessContact.verification_status == "verified"),
        )
    ):
        kinds[bid].add(kind)
    reasons: dict[uuid.UUID, str] = {}
    for a in await db.scalars(
        select(LeadAssessment).where(LeadAssessment.business_id.in_(ids)).order_by(LeadAssessment.created_at.desc())
    ):
        if a.business_id in reasons:
            continue
        # The business's own gaps, not the pitch: the opportunity text names the showcase seller's services.
        problem = next((str(x) for x in a.potential_problems or [] if str(x).strip()), "")
        reasons[a.business_id] = _first_sentence(problem or a.summary or "")
    return {
        "count": int(count),
        "searched_at": searched_at,
        "samples": [
            {
                "name": mask_name(b.name),
                "city": b.city,
                "score": round(b.latest_score) if b.latest_score is not None else None,
                "reason": reasons.get(b.id, ""),
                "contact_types": sorted(kinds[b.id]),
            }
            for b in top
        ],
    }
