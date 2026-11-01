import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import delete, select

from app.api.deps import DB, CurrentPrincipal, audit, require_role
from app.core.errors import Conflict, NotFound
from app.models import (
    Business,
    BusinessContact,
    BusinessEvidence,
    BusinessSource,
    Campaign,
    CampaignLead,
    CampaignRun,
    LeadAssessment,
    LeadNote,
    LeadScore,
    LeadTag,
    OutreachActivity,
    OutreachDraft,
    SuppressionEntry,
    Workspace,
)
from app.models.enums import (
    ACTIVE_STATUSES,
    CampaignStatus,
    ContactType,
    CrmStatus,
    Role,
    SuppressionKind,
    VerificationStatus,
)
from app.research.analysis.ai_service import AI_PROVIDERS, AIRefused, AIService, AIUnavailable
from app.research.analysis.heuristic import template_pitch
from app.research.enrichment.normalize import (
    business_domain,
    normalize_email,
    normalize_name,
    normalize_phone,
)
from app.research.pipeline import CampaignPipeline, StopRun
from app.schemas.common import Message, Page
from app.schemas.lead import (
    ActivityOut,
    AssessmentOut,
    BulkAction,
    ContactOut,
    ContactUpdate,
    DraftOut,
    EvidenceOut,
    LeadCreate,
    LeadDetail,
    LeadRow,
    LeadUpdate,
    NoteIn,
    NoteOut,
    PitchIn,
    ScoreOut,
    SourceOut,
    SuppressionIn,
    SuppressionOut,
    TagIn,
)
from app.services import campaigns as campaign_svc
from app.services import credits as credit_svc
from app.services import providers as provider_svc
from app.services.leads import LeadFilters, get_business, paged_leads
from app.services.profile import get_profile, offering_map, offering_name
from app.services.suppression import (
    apply_suppression,
    business_is_suppressed,
    normalize_suppression,
    outreach_eligible,
    suppression_sets,
)

router = APIRouter(prefix="/leads", tags=["leads"])
contacts_router = APIRouter(prefix="/contacts", tags=["contacts"])
suppression_router = APIRouter(prefix="/suppression", tags=["suppression"])


def filters_dep(
    q: str | None = Query(None, max_length=200),
    country: str | None = None,
    city: str | None = None,
    industry: str | None = None,
    campaign_id: uuid.UUID | None = None,
    priority: str | None = None,
    crm_status: str | None = None,
    min_score: float | None = Query(None, ge=0, le=100),
    max_score: float | None = Query(None, ge=0, le=100),
    has_contact: bool | None = None,
    verified_only: bool | None = None,
    source: str | None = None,
    tag: str | None = None,
    is_demo: bool | None = None,
    service: str | None = None,
    qualified_only: bool | None = None,
) -> LeadFilters:
    return LeadFilters(
        q=q,
        country=country,
        city=city,
        industry=industry,
        campaign_id=campaign_id,
        priority=priority,
        crm_status=crm_status,
        min_score=min_score,
        max_score=max_score,
        has_contact=has_contact,
        verified_only=verified_only,
        source=source,
        tag=tag,
        is_demo=is_demo,
        service=service,
        qualified_only=qualified_only,
    )


Filters = Depends(filters_dep)


@router.get("", response_model=Page[LeadRow])
async def list_leads(
    p: CurrentPrincipal,
    db: DB,
    f: LeadFilters = Filters,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    sort: str = "score",
    order: str = Query("desc", pattern="^(asc|desc)$"),
) -> Page[LeadRow]:
    rows, total = await paged_leads(db, p.workspace_id, f, page=page, page_size=page_size, sort=sort, order=order)
    return Page(
        items=[LeadRow(**{k: v for k, v in r.items() if not k.startswith("_")}) for r in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("", response_model=LeadRow, status_code=201, dependencies=[require_role(Role.ANALYST)])
async def create_lead(body: LeadCreate, p: CurrentPrincipal, db: DB) -> LeadRow:
    url = str(body.website_url) if body.website_url else None
    domain = business_domain(url)
    if domain and await db.scalar(
        select(Business.id).where(
            Business.workspace_id == p.workspace_id, Business.normalized_domain == domain, Business.deleted_at.is_(None)
        )
    ):
        raise Conflict(f"A lead with domain {domain} already exists")
    b = Business(
        workspace_id=p.workspace_id,
        name=body.name,
        normalized_name=normalize_name(body.name),
        website_url=url,
        normalized_domain=domain,
        industry=body.industry,
        country=body.country.upper() if body.country else None,
        city=body.city,
        description=body.description,
        is_manual=True,
    )
    db.add(b)
    await db.flush()
    src = str(body.source_url) if body.source_url else (url or "manual-entry")
    db.add(BusinessSource(business_id=b.id, provider_key="manual", source_url=src, title="Manual entry"))
    sets = await suppression_sets(db, p.workspace_id)
    if body.email:
        e = normalize_email(body.email)
        if not e:
            raise Conflict("Invalid email")
        db.add(
            BusinessContact(
                business_id=b.id,
                type=ContactType.EMAIL,
                value=e,
                normalized_value=e,
                source_url=src,
                source_provider="manual",
                verification_status=VerificationStatus.UNVERIFIED,
                confidence=0.5,
                is_suppressed=e in sets["email"],
            )
        )
    if body.phone:
        ph = normalize_phone(body.phone, b.country)
        if not ph:
            raise Conflict("Invalid phone number for the given country")
        db.add(
            BusinessContact(
                business_id=b.id,
                type=ContactType.PHONE,
                value=body.phone,
                normalized_value=ph,
                source_url=src,
                source_provider="manual",
                verification_status=VerificationStatus.UNVERIFIED,
                confidence=0.5,
                is_suppressed=ph in sets["phone"],
            )
        )
    b.contact_count = int(bool(body.email)) + int(bool(body.phone))
    db.add(OutreachActivity(business_id=b.id, user_id=p.user.id, type="created", payload={"manual": True}))
    await audit(db, p, "lead.created", "business", b.id)
    await db.commit()
    rows, _ = await paged_leads(
        db, p.workspace_id, LeadFilters(ids=[b.id]), page=1, page_size=1, sort="score", order="desc"
    )
    return LeadRow(**{k: v for k, v in rows[0].items() if not k.startswith("_")})


@router.post("/bulk", response_model=Message, dependencies=[require_role(Role.ANALYST)])
async def bulk_action(body: BulkAction, p: CurrentPrincipal, db: DB) -> Message:
    rows = list(
        await db.scalars(
            select(Business).where(
                Business.workspace_id == p.workspace_id, Business.id.in_(body.ids), Business.deleted_at.is_(None)
            )
        )
    )
    if body.action == "set_status":
        status = CrmStatus(body.value or "")
        for b in rows:
            if (
                b.crm_status == CrmStatus.DO_NOT_CONTACT
                and status != CrmStatus.DO_NOT_CONTACT
                and p.role not in (Role.ADMIN, Role.OWNER)
            ):
                continue  # only admins can lift a do-not-contact flag
            db.add(
                OutreachActivity(
                    business_id=b.id,
                    user_id=p.user.id,
                    type="status_change",
                    payload={"from": b.crm_status, "to": status.value},
                )
            )
            b.crm_status = status
    elif body.action in ("add_tag", "remove_tag"):
        tag = (body.value or "").strip()[:60]
        if not tag:
            raise Conflict("Tag value required")
        for b in rows:
            if body.action == "add_tag":
                if not await db.scalar(select(LeadTag.id).where(LeadTag.business_id == b.id, LeadTag.tag == tag)):
                    db.add(LeadTag(business_id=b.id, tag=tag))
            else:
                await db.execute(delete(LeadTag).where(LeadTag.business_id == b.id, LeadTag.tag == tag))
    elif body.action == "suppress":
        for b in rows:
            await _suppress_business(db, p, b, body.value or "Bulk suppression")
    elif body.action == "delete":
        p.require(Role.ADMIN)
        for b in rows:
            b.deleted_at = datetime.now(UTC)
    await audit(db, p, f"lead.bulk.{body.action}", "business", None, {"count": len(rows), "value": body.value})
    await db.commit()
    return Message(message=f"{body.action} applied to {len(rows)} leads")


async def _suppress_business(db, p, b: Business, reason: str) -> None:  # noqa: ANN001
    b.crm_status = CrmStatus.DO_NOT_CONTACT
    exists_ = await db.scalar(
        select(SuppressionEntry.id).where(
            SuppressionEntry.workspace_id == p.workspace_id,
            SuppressionEntry.kind == SuppressionKind.BUSINESS,
            SuppressionEntry.value == str(b.id),
        )
    )
    if not exists_:
        db.add(
            SuppressionEntry(
                workspace_id=p.workspace_id,
                kind=SuppressionKind.BUSINESS,
                value=str(b.id),
                reason=reason,
                created_by=p.user.id,
            )
        )
    if b.normalized_domain and not await db.scalar(
        select(SuppressionEntry.id).where(
            SuppressionEntry.workspace_id == p.workspace_id,
            SuppressionEntry.kind == SuppressionKind.DOMAIN,
            SuppressionEntry.value == b.normalized_domain,
        )
    ):
        db.add(
            SuppressionEntry(
                workspace_id=p.workspace_id,
                kind=SuppressionKind.DOMAIN,
                value=b.normalized_domain,
                reason=reason,
                created_by=p.user.id,
            )
        )
    db.add(OutreachActivity(business_id=b.id, user_id=p.user.id, type="suppressed", payload={"reason": reason}))
    await db.flush()
    await apply_suppression(db, p.workspace_id)


@router.get("/{lead_id}", response_model=LeadDetail)
async def lead_detail(lead_id: uuid.UUID, p: CurrentPrincipal, db: DB) -> LeadDetail:
    b = await get_business(db, p.workspace_id, lead_id)
    contacts = list(
        await db.scalars(
            select(BusinessContact)
            .where(BusinessContact.business_id == b.id)
            .order_by(BusinessContact.type, BusinessContact.confidence.desc())
        )
    )
    sources = list(
        await db.scalars(
            select(BusinessSource).where(BusinessSource.business_id == b.id).order_by(BusinessSource.discovered_at)
        )
    )
    evidence = list(
        await db.scalars(
            select(BusinessEvidence)
            .where(BusinessEvidence.business_id == b.id)
            .order_by(BusinessEvidence.kind, BusinessEvidence.signal_key)
        )
    )
    assessments = list(
        await db.scalars(
            select(LeadAssessment)
            .where(LeadAssessment.business_id == b.id)
            .order_by(LeadAssessment.created_at.desc())
            .limit(10)
        )
    )
    score = await db.scalar(
        select(LeadScore).where(LeadScore.business_id == b.id).order_by(LeadScore.created_at.desc()).limit(1)
    )
    camp_rows = (
        await db.execute(
            select(
                Campaign.id,
                Campaign.name,
                Campaign.status,
                CampaignLead.score,
                CampaignLead.priority,
                CampaignLead.qualified,
                CampaignLead.created_at,
                CampaignLead.discovered_via,
            )
            .join(CampaignLead, CampaignLead.campaign_id == Campaign.id)
            .where(CampaignLead.business_id == b.id, Campaign.deleted_at.is_(None))
            .order_by(CampaignLead.created_at.desc())
        )
    ).all()
    notes = list(
        await db.scalars(select(LeadNote).where(LeadNote.business_id == b.id).order_by(LeadNote.created_at.desc()))
    )
    tags = sorted(await db.scalars(select(LeadTag.tag).where(LeadTag.business_id == b.id)))
    activities = list(
        await db.scalars(
            select(OutreachActivity)
            .where(OutreachActivity.business_id == b.id)
            .order_by(OutreachActivity.created_at.desc())
            .limit(50)
        )
    )
    drafts = list(
        await db.scalars(
            select(OutreachDraft)
            .where(OutreachDraft.business_id == b.id)
            .order_by(OutreachDraft.created_at.desc())
            .limit(10)
        )
    )
    sets = await suppression_sets(db, p.workspace_id)
    return LeadDetail(
        business={c.name: getattr(b, c.name) for c in Business.__table__.columns},
        contacts=[ContactOut.model_validate(c) for c in contacts],
        sources=[SourceOut.model_validate(s) for s in sources],
        evidence=[EvidenceOut.model_validate(e) for e in evidence],
        assessment=AssessmentOut.model_validate(assessments[0]) if assessments else None,
        assessments=[AssessmentOut.model_validate(a) for a in assessments],
        score=ScoreOut.model_validate(score) if score else None,
        campaigns=[
            {
                "id": str(r[0]),
                "name": r[1],
                "status": r[2],
                "score": r[3],
                "priority": r[4],
                "qualified": r[5],
                "added_at": r[6],
                "discovered_via": r[7],
            }
            for r in camp_rows
        ],
        notes=[NoteOut.model_validate(n) for n in notes],
        tags=tags,
        activities=[ActivityOut.model_validate(a) for a in activities],
        drafts=[DraftOut.model_validate(d) for d in drafts],
        outreach_eligible=outreach_eligible(b, contacts, sets),
        suppressed=business_is_suppressed(b, sets),
    )


@router.patch("/{lead_id}", response_model=Message, dependencies=[require_role(Role.ANALYST)])
async def update_lead(lead_id: uuid.UUID, body: LeadUpdate, p: CurrentPrincipal, db: DB) -> Message:
    b = await get_business(db, p.workspace_id, lead_id)
    changes = body.model_dump(exclude_unset=True)
    if "crm_status" in changes:
        new = changes.pop("crm_status")
        if b.crm_status == CrmStatus.DO_NOT_CONTACT and new != CrmStatus.DO_NOT_CONTACT:
            p.require(Role.ADMIN)
            sets = await suppression_sets(db, p.workspace_id)
            if str(b.id) in sets["business"] or (b.normalized_domain or "") in sets["domain"]:
                raise Conflict("This business is on the suppression list; remove the suppression entry first")
        if new == CrmStatus.DO_NOT_CONTACT:
            await _suppress_business(db, p, b, "Marked Do Not Contact")
        else:
            db.add(
                OutreachActivity(
                    business_id=b.id, user_id=p.user.id, type="status_change", payload={"from": b.crm_status, "to": new}
                )
            )
            b.crm_status = new
    if "website_url" in changes:
        url = changes.pop("website_url")
        domain = business_domain(url)
        if (
            domain
            and domain != b.normalized_domain
            and await db.scalar(
                select(Business.id).where(
                    Business.workspace_id == p.workspace_id,
                    Business.normalized_domain == domain,
                    Business.deleted_at.is_(None),
                )
            )
        ):
            raise Conflict(f"Another lead already uses {domain}")
        b.website_url, b.normalized_domain = url, domain
    for k, v in changes.items():
        setattr(b, k, v)
    if "name" in changes:
        b.normalized_name = normalize_name(b.name)
    if changes:
        db.add(OutreachActivity(business_id=b.id, user_id=p.user.id, type="edit", payload={"fields": list(changes)}))
    await audit(db, p, "lead.updated", "business", b.id, {"fields": list(body.model_dump(exclude_unset=True))})
    await db.commit()
    return Message(message="Lead updated")


@router.delete("/{lead_id}", response_model=Message, dependencies=[require_role(Role.ADMIN)])
async def delete_lead(lead_id: uuid.UUID, p: CurrentPrincipal, db: DB, hard: bool = False) -> Message:
    b = await get_business(db, p.workspace_id, lead_id)
    if hard:
        await db.delete(b)
    else:
        b.deleted_at = datetime.now(UTC)
    await audit(db, p, "lead.deleted", "business", lead_id, {"hard": hard})
    await db.commit()
    return Message(message="Lead permanently deleted" if hard else "Lead deleted")


@router.post("/{lead_id}/notes", response_model=NoteOut, status_code=201, dependencies=[require_role(Role.ANALYST)])
async def add_note(lead_id: uuid.UUID, body: NoteIn, p: CurrentPrincipal, db: DB) -> NoteOut:
    b = await get_business(db, p.workspace_id, lead_id)
    note = LeadNote(business_id=b.id, author_id=p.user.id, body=body.body)
    db.add(note)
    db.add(OutreachActivity(business_id=b.id, user_id=p.user.id, type="note", payload={}))
    await db.commit()
    return NoteOut.model_validate(note)


@router.post("/{lead_id}/tags", response_model=Message, dependencies=[require_role(Role.ANALYST)])
async def add_tag(lead_id: uuid.UUID, body: TagIn, p: CurrentPrincipal, db: DB) -> Message:
    b = await get_business(db, p.workspace_id, lead_id)
    tag = body.tag.strip()
    if not await db.scalar(select(LeadTag.id).where(LeadTag.business_id == b.id, LeadTag.tag == tag)):
        db.add(LeadTag(business_id=b.id, tag=tag))
        db.add(OutreachActivity(business_id=b.id, user_id=p.user.id, type="tag", payload={"add": tag}))
        await db.commit()
    return Message(message="Tag added")


@router.delete("/{lead_id}/tags/{tag}", response_model=Message, dependencies=[require_role(Role.ANALYST)])
async def remove_tag(lead_id: uuid.UUID, tag: str, p: CurrentPrincipal, db: DB) -> Message:
    b = await get_business(db, p.workspace_id, lead_id)
    await db.execute(delete(LeadTag).where(LeadTag.business_id == b.id, LeadTag.tag == tag))
    await db.commit()
    return Message(message="Tag removed")


@router.post("/{lead_id}/pitch", response_model=DraftOut, status_code=201, dependencies=[require_role(Role.ANALYST)])
async def generate_pitch(lead_id: uuid.UUID, body: PitchIn, p: CurrentPrincipal, db: DB) -> DraftOut:
    """Generate outreach DRAFTS for human review. Nothing is ever sent automatically."""
    b = await get_business(db, p.workspace_id, lead_id)
    sets = await suppression_sets(db, p.workspace_id)
    if business_is_suppressed(b, sets):
        raise Conflict("This business is marked Do Not Contact; drafts cannot be generated")
    a = await db.scalar(
        select(LeadAssessment)
        .where(LeadAssessment.business_id == b.id)
        .order_by(LeadAssessment.created_at.desc())
        .limit(1)
    )
    service = body.service or (a.recommended_services[0]["service"] if a and a.recommended_services else None)
    profile = await get_profile(db, p.workspace_id)
    offering = offering_map(profile).get(service or "")
    snapshot = next((r.get("name") for r in (a.recommended_services if a else []) if r.get("service") == service), None)
    person = await db.scalar(
        select(BusinessContact)
        .where(
            BusinessContact.business_id == b.id,
            BusinessContact.type == ContactType.PERSON,
            BusinessContact.is_suppressed.is_(False),
        )
        .order_by(BusinessContact.confidence.desc())
        .limit(1)
    )
    context = {
        "company": b.name,
        "website": b.website_url,
        "industry": b.industry,
        "city": b.city,
        "country": b.country,
        "description": b.description,
        "observations": [s["signal"] for s in (a.observed_signals if a else [])][:5],
        "potential_needs": (a.potential_problems if a else [])[:3],
        "service": service,
        "service_name": (offering or {}).get("name") or snapshot or offering_name({}, service, body.language),
        "offering_description": (offering or {}).get("description") or None,
        "seller_company": profile.company_name or None,
        "seller_value_proposition": profile.value_proposition or None,
        "decision_maker": (
            {"name": person.person_name, "role": person.person_role} if person and person.person_name else None
        ),
        "opportunity": a.opportunity if a else None,
    }
    creds = {}
    for key in AI_PROVIDERS:
        c, _ = await provider_svc.credentials_for(db, p.workspace_id, key)
        if c:
            creds[key] = c
    ai = AIService(creds)
    provider, cost = "template", 0.0
    if ai.available and not b.is_demo:
        try:
            result = await ai.generate_pitch(
                context=context,
                language=body.language,
                tone=body.tone,
                length=body.length,
                sender=" - ".join(x for x in (profile.sender_name or p.user.full_name, profile.company_name) if x)
                or "our team",
            )
            draft_data = result.output.model_dump()
            provider, cost = result.provider, result.cost_usd
        except (AIUnavailable, AIRefused):
            draft_data = template_pitch(context, body.language)
    else:
        draft_data = template_pitch(context, body.language)
        provider = "demo-template" if b.is_demo else "template"
    draft = OutreachDraft(
        business_id=b.id,
        author_id=p.user.id,
        language=body.language,
        tone=body.tone,
        length=body.length,
        service=service,
        provider=provider,
        cost_usd=cost,
        **draft_data,
    )
    db.add(draft)
    db.add(
        OutreachActivity(
            business_id=b.id,
            user_id=p.user.id,
            type="draft_created",
            payload={"language": body.language, "provider": provider},
        )
    )
    await db.commit()
    return DraftOut.model_validate(draft)


@router.post("/{lead_id}/reanalyze", response_model=Message, dependencies=[require_role(Role.ANALYST)])
async def reanalyze(lead_id: uuid.UUID, p: CurrentPrincipal, db: DB) -> Message:
    """Re-run analysis+scoring for one lead within its most recent campaign context."""
    b = await get_business(db, p.workspace_id, lead_id)
    lead = await db.scalar(
        select(CampaignLead).where(CampaignLead.business_id == b.id).order_by(CampaignLead.created_at.desc()).limit(1)
    )
    if lead is None:
        raise NotFound("This lead is not part of any campaign; add it to a campaign to analyse it")

    campaign = await db.get(Campaign, lead.campaign_id)
    if campaign.status in ACTIVE_STATUSES:
        raise Conflict("The campaign is running; re-analyse this lead after it finishes")
    if campaign.status == CampaignStatus.CANCELLED:
        raise Conflict("The campaign was cancelled; leads of a cancelled campaign cannot be re-analysed")
    await campaign_svc.ensure_can_run(db, campaign)  # AI analysis is paid work too
    await db.refresh(campaign, attribute_names=["sources"])
    run = await db.scalar(
        select(CampaignRun)
        .where(CampaignRun.campaign_id == campaign.id)
        .order_by(CampaignRun.run_number.desc())
        .limit(1)
    )
    pipe = CampaignPipeline(db, campaign, run)
    pipe.workspace = await db.get(Workspace, campaign.workspace_id)
    pipe.only_business = b.id
    # The campaign's budget still applies; pause/runtime caps belong to the run, not to this one-off request.
    pipe.check_control = pipe.check_budget  # type: ignore[method-assign]
    try:
        await pipe.check_budget()
        lead.analyzed = False
        lead.scored = False
        await pipe.stage_analysis()
        await pipe.stage_scoring()
    except StopRun as stop:
        await db.rollback()
        if stop.code == "credits_exhausted":
            raise credit_svc.InsufficientCredits("You have no credits left; top up to re-analyse leads") from stop
        raise Conflict("The campaign's maximum budget is reached; raise it to re-analyse leads") from stop
    return Message(message="Lead re-analysed")


@contacts_router.patch("/{contact_id}", response_model=ContactOut, dependencies=[require_role(Role.ANALYST)])
async def update_contact(contact_id: uuid.UUID, body: ContactUpdate, p: CurrentPrincipal, db: DB) -> ContactOut:
    c = await db.scalar(
        select(BusinessContact)
        .join(Business, Business.id == BusinessContact.business_id)
        .where(BusinessContact.id == contact_id, Business.workspace_id == p.workspace_id)
    )
    if c is None:
        raise NotFound("Contact not found")
    if body.verification_status is not None:
        if body.verification_status == VerificationStatus.VERIFIED:
            raise Conflict("Contacts can only be marked verified by a verification provider")
        c.verification_status = body.verification_status
    if body.is_suppressed is not None:
        if body.is_suppressed:
            kind = SuppressionKind.EMAIL if c.type == ContactType.EMAIL else SuppressionKind.PHONE
            if c.type in (ContactType.EMAIL, ContactType.PHONE, ContactType.WHATSAPP):
                if not await db.scalar(
                    select(SuppressionEntry.id).where(
                        SuppressionEntry.workspace_id == p.workspace_id,
                        SuppressionEntry.kind == kind,
                        SuppressionEntry.value == c.normalized_value,
                    )
                ):
                    db.add(
                        SuppressionEntry(
                            workspace_id=p.workspace_id,
                            kind=kind,
                            value=c.normalized_value,
                            reason="Suppressed from lead page",
                            created_by=p.user.id,
                        )
                    )
        else:
            p.require(Role.ADMIN)
            await db.execute(
                delete(SuppressionEntry).where(
                    SuppressionEntry.workspace_id == p.workspace_id, SuppressionEntry.value == c.normalized_value
                )
            )
        c.is_suppressed = body.is_suppressed
    await audit(db, p, "contact.updated", "contact", c.id, body.model_dump(exclude_none=True))
    await db.commit()
    return ContactOut.model_validate(c)


@suppression_router.get("", response_model=list[SuppressionOut])
async def list_suppression(p: CurrentPrincipal, db: DB) -> list[SuppressionOut]:
    rows = await db.scalars(
        select(SuppressionEntry)
        .where(SuppressionEntry.workspace_id == p.workspace_id)
        .order_by(SuppressionEntry.created_at.desc())
    )
    return [SuppressionOut.model_validate(r) for r in rows]


@suppression_router.post("", response_model=SuppressionOut, status_code=201, dependencies=[require_role(Role.ANALYST)])
async def add_suppression(body: SuppressionIn, p: CurrentPrincipal, db: DB) -> SuppressionOut:
    value = normalize_suppression(body.kind, body.value)
    if not value:
        raise Conflict(f"Invalid {body.kind.value} value")
    existing = await db.scalar(
        select(SuppressionEntry).where(
            SuppressionEntry.workspace_id == p.workspace_id,
            SuppressionEntry.kind == body.kind,
            SuppressionEntry.value == value,
        )
    )
    if existing:
        return SuppressionOut.model_validate(existing)
    entry = SuppressionEntry(
        workspace_id=p.workspace_id, kind=body.kind, value=value, reason=body.reason, created_by=p.user.id
    )
    db.add(entry)
    await db.flush()
    await apply_suppression(db, p.workspace_id)
    await audit(db, p, "suppression.added", "suppression", entry.id, {"kind": body.kind.value})
    await db.commit()
    return SuppressionOut.model_validate(entry)


@suppression_router.delete("/{entry_id}", response_model=Message, dependencies=[require_role(Role.ADMIN)])
async def remove_suppression(entry_id: uuid.UUID, p: CurrentPrincipal, db: DB) -> Message:
    entry = await db.scalar(
        select(SuppressionEntry).where(SuppressionEntry.id == entry_id, SuppressionEntry.workspace_id == p.workspace_id)
    )
    if entry is None:
        raise NotFound("Entry not found")
    await db.delete(entry)
    await db.flush()
    await apply_suppression(db, p.workspace_id)
    await audit(db, p, "suppression.removed", "suppression", entry_id)
    await db.commit()
    return Message(message="Suppression entry removed (Do Not Contact statuses are not reverted automatically)")
