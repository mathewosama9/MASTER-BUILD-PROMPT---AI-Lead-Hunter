"""Lead (business) queries shared by the leads API, exports and Telegram."""

import uuid
from collections import defaultdict
from datetime import datetime

from sqlalchemy import Select, and_, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFound
from app.models import (
    Business,
    BusinessContact,
    BusinessSource,
    Campaign,
    CampaignLead,
    LeadTag,
)
from app.models.enums import ContactType, CrmStatus, VerificationStatus
from app.schemas.lead import ContactOut
from app.services.suppression import outreach_eligible, suppression_sets


class LeadFilters:
    def __init__(
        self,
        *,
        q: str | None = None,
        country: str | None = None,
        city: str | None = None,
        industry: str | None = None,
        campaign_id: uuid.UUID | None = None,
        priority: str | None = None,
        crm_status: str | None = None,
        min_score: float | None = None,
        max_score: float | None = None,
        has_contact: bool | None = None,
        verified_only: bool | None = None,
        source: str | None = None,
        tag: str | None = None,
        is_demo: bool | None = None,
        service: str | None = None,
        ids: list[uuid.UUID] | None = None,
        qualified_only: bool | None = None,
        updated_after: datetime | None = None,
    ) -> None:
        self.__dict__.update(locals())
        self.__dict__.pop("self")


SORTS = {
    "score": Business.latest_score,
    "name": Business.name,
    "updated_at": Business.updated_at,
    "created_at": Business.created_at,
    "crm_status": Business.crm_status,
    "country": Business.country,
}


def lead_query(workspace_id: uuid.UUID, f: LeadFilters) -> Select:
    stmt = select(Business).where(Business.workspace_id == workspace_id, Business.deleted_at.is_(None))
    if f.ids:
        stmt = stmt.where(Business.id.in_(f.ids))
    if f.q:
        like = f"%{f.q.strip()}%"
        stmt = stmt.where(
            or_(
                Business.name.ilike(like),
                Business.normalized_domain.ilike(like),
                Business.description.ilike(like),
                Business.city.ilike(like),
                exists().where(
                    and_(BusinessContact.business_id == Business.id, BusinessContact.normalized_value.ilike(like))
                ),
            )
        )
    if f.country:
        stmt = stmt.where(Business.country.in_(f.country.upper().split(",")))
    if f.city:
        stmt = stmt.where(Business.city.ilike(f.city))
    if f.industry:
        stmt = stmt.where(Business.industry.in_(f.industry.split(",")))
    if f.priority:
        stmt = stmt.where(Business.latest_priority.in_(f.priority.split(",")))
    if f.crm_status:
        stmt = stmt.where(Business.crm_status.in_(f.crm_status.split(",")))
    if f.min_score is not None:
        stmt = stmt.where(Business.latest_score >= f.min_score)
    if f.max_score is not None:
        stmt = stmt.where(Business.latest_score <= f.max_score)
    if f.service:
        stmt = stmt.where(Business.recommended_service == f.service)
    if f.has_contact is True:
        stmt = stmt.where(Business.contact_count > 0)
    elif f.has_contact is False:
        stmt = stmt.where(Business.contact_count == 0)
    if f.verified_only:
        stmt = stmt.where(Business.has_verified_contact.is_(True))
    if f.is_demo is not None:
        stmt = stmt.where(Business.is_demo.is_(f.is_demo))
    if f.updated_after:
        stmt = stmt.where(Business.updated_at >= f.updated_after)
    if f.campaign_id or f.qualified_only:
        cond = [CampaignLead.business_id == Business.id]
        if f.campaign_id:
            cond.append(CampaignLead.campaign_id == f.campaign_id)
        if f.qualified_only:
            cond.append(CampaignLead.qualified.is_(True))
        stmt = stmt.where(exists().where(and_(*cond)))
    if f.source:
        stmt = stmt.where(
            exists().where(and_(BusinessSource.business_id == Business.id, BusinessSource.provider_key == f.source))
        )
    if f.tag:
        stmt = stmt.where(exists().where(and_(LeadTag.business_id == Business.id, LeadTag.tag == f.tag)))
    return stmt


async def paged_leads(
    db: AsyncSession, workspace_id: uuid.UUID, f: LeadFilters, *, page: int, page_size: int, sort: str, order: str
) -> tuple[list[dict], int]:
    stmt = lead_query(workspace_id, f)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    col = SORTS.get(sort, Business.latest_score)
    ordering = col.desc().nulls_last() if order == "desc" else col.asc().nulls_last()
    rows = list(await db.scalars(stmt.order_by(ordering, Business.id).offset((page - 1) * page_size).limit(page_size)))
    return await decorate(db, workspace_id, rows), total


async def decorate(db: AsyncSession, workspace_id: uuid.UUID, rows: list[Business]) -> list[dict]:
    ids = [b.id for b in rows]
    if not ids:
        return []
    sources: dict[uuid.UUID, set[str]] = defaultdict(set)
    for bid, key in (
        await db.execute(
            select(BusinessSource.business_id, BusinessSource.provider_key).where(BusinessSource.business_id.in_(ids))
        )
    ).all():
        sources[bid].add(key)
    campaigns: dict[uuid.UUID, list[dict]] = defaultdict(list)
    for bid, cid, name, score in (
        await db.execute(
            select(CampaignLead.business_id, Campaign.id, Campaign.name, CampaignLead.score)
            .join(Campaign, Campaign.id == CampaignLead.campaign_id)
            .where(CampaignLead.business_id.in_(ids), Campaign.deleted_at.is_(None))
        )
    ).all():
        campaigns[bid].append({"id": str(cid), "name": name, "score": score})
    tags: dict[uuid.UUID, list[str]] = defaultdict(list)
    for bid, tag in (
        await db.execute(select(LeadTag.business_id, LeadTag.tag).where(LeadTag.business_id.in_(ids)))
    ).all():
        tags[bid].append(tag)
    contacts: dict[uuid.UUID, list[BusinessContact]] = defaultdict(list)
    for c in await db.scalars(select(BusinessContact).where(BusinessContact.business_id.in_(ids))):
        contacts[c.business_id].append(c)
    sets = await suppression_sets(db, workspace_id)
    out = []
    for b in rows:
        out.append(
            {
                "id": b.id,
                "name": b.name,
                "website_url": b.website_url,
                "normalized_domain": b.normalized_domain,
                "country": b.country,
                "city": b.city,
                "industry": b.industry,
                "latest_score": b.latest_score,
                "latest_priority": b.latest_priority,
                "recommended_service": b.recommended_service,
                "crm_status": b.crm_status,
                "contact_count": b.contact_count,
                "has_verified_contact": b.has_verified_contact,
                "is_demo": b.is_demo,
                "sources": sorted(sources[b.id]),
                "campaigns": campaigns[b.id],
                "tags": sorted(tags[b.id]),
                "outreach_eligible": outreach_eligible(b, contacts[b.id], sets),
                "updated_at": b.updated_at,
                "_contacts": contacts[b.id],
            }
        )
    return out


async def get_business(db: AsyncSession, workspace_id: uuid.UUID, business_id: uuid.UUID) -> Business:
    b = await db.scalar(
        select(Business).where(
            Business.id == business_id, Business.workspace_id == workspace_id, Business.deleted_at.is_(None)
        )
    )
    if b is None:
        raise NotFound("Lead not found")
    return b


PUBLIC_PROOF_KINDS = ("first_party", "professional", "third_party")  # people databases stay unnamed


def delivered_contacts(contacts: list[BusinessContact]) -> list[ContactOut]:
    """Contacts as the customer sees them: only VERIFIED decision makers. A channel saved under a person who
    is not verified (earlier runs) stays as a plain business contact, without the name."""
    verified = {
        c.person_name
        for c in contacts
        if c.type == ContactType.PERSON and c.verification_status == VerificationStatus.VERIFIED
    }
    out: list[ContactOut] = []
    for c in contacts:
        if c.type == ContactType.PERSON and c.verification_status != VerificationStatus.VERIFIED:
            continue
        item = ContactOut.model_validate(c)
        ev = c.evidence or {}
        if c.type == ContactType.PERSON:
            item.proof_links = [
                p["url"] for p in ev.get("proofs", []) if p.get("kind") in PUBLIC_PROOF_KINDS and p.get("url")
            ][:5]
            item.sources_count = ev.get("sources_count")
        elif ev.get("sources"):
            item.sources_count = len(set(ev["sources"]))
        if c.person_name and c.type != ContactType.PERSON and c.person_name not in verified:
            item.person_name = item.person_role = None
            item.subtype = None if item.subtype == "decision_maker" else item.subtype
        out.append(item)
    return out


def best_contact(contacts: list[BusinessContact], ctype: ContactType) -> BusinessContact | None:
    usable = [
        c
        for c in contacts
        if c.type == ctype and not c.is_suppressed and c.verification_status != VerificationStatus.INVALID
    ]
    rank = {VerificationStatus.VERIFIED: 0, VerificationStatus.UNVERIFIED: 1, VerificationStatus.DISCOVERED: 1}
    usable.sort(key=lambda c: (rank.get(c.verification_status, 2), -c.confidence))
    return usable[0] if usable else None


TERMINAL_CRM = {CrmStatus.DO_NOT_CONTACT}
