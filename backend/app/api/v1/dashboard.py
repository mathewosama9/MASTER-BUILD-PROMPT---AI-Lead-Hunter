from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Query
from sqlalchemy import case, func, select

from app.api.deps import DB, CurrentPrincipal
from app.models import (
    Business,
    BusinessContact,
    BusinessSource,
    Campaign,
    CampaignLead,
    CreditTransaction,
    JobEvent,
    LeadAssessment,
    OutreachDraft,
    ProviderUsage,
    TelegramAccount,
    WorkspaceProfile,
)
from app.models.enums import (
    ACTIVE_STATUSES,
    CampaignStatus,
    ContactType,
    CreditKind,
    CrmStatus,
    TelegramLinkStatus,
    VerificationStatus,
)

# Lead statuses that mean "someone already reached out".
REACHED = [CrmStatus.CONTACTED, CrmStatus.REPLIED, CrmStatus.MEETING_SCHEDULED, CrmStatus.WON, CrmStatus.LOST]
# Lead statuses still waiting for a first contact.
TO_CONTACT = [CrmStatus.NEW, CrmStatus.REVIEWED, CrmStatus.QUALIFIED, CrmStatus.READY_FOR_OUTREACH]

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/stats")
async def stats(
    p: CurrentPrincipal, db: DB, is_demo: bool | None = Query(None), days: int = Query(30, ge=7, le=365)
) -> dict:
    """All numbers are computed from the database on each request."""
    ws = p.workspace_id
    now = datetime.now(UTC)
    start_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    biz = [Business.workspace_id == ws, Business.deleted_at.is_(None)]
    camp = [Campaign.workspace_id == ws, Campaign.deleted_at.is_(None)]
    if is_demo is not None:
        biz.append(Business.is_demo.is_(is_demo))
        camp.append(Campaign.is_demo.is_(is_demo))

    total, with_contact, verified, avg_score = (
        await db.execute(
            select(
                func.count(),
                func.count().filter(Business.contact_count > 0),
                func.count().filter(Business.has_verified_contact.is_(True)),
                func.avg(Business.latest_score),
            ).where(*biz)
        )
    ).one()
    qualified = (
        await db.scalar(
            select(func.count(func.distinct(CampaignLead.business_id)))
            .join(Business, Business.id == CampaignLead.business_id)
            .where(*biz, CampaignLead.qualified.is_(True))
        )
        or 0
    )

    def since(d: datetime):  # noqa: ANN202
        return func.count().filter(Business.created_at >= d)

    today, week, month = (
        await db.execute(
            select(since(start_day), since(now - timedelta(days=7)), since(now - timedelta(days=30))).where(*biz)
        )
    ).one()

    status_counts = dict(
        (await db.execute(select(Campaign.status, func.count()).where(*camp).group_by(Campaign.status))).all()
    )
    active = sum(v for k, v in status_counts.items() if k in {s.value for s in ACTIVE_STATUSES})
    completed = status_counts.get(CampaignStatus.COMPLETED, 0) + status_counts.get(
        CampaignStatus.PARTIALLY_COMPLETED, 0
    )

    ai_cost = (
        await db.scalar(
            select(func.coalesce(func.sum(LeadAssessment.cost_usd), 0.0))
            .join(Business, Business.id == LeadAssessment.business_id)
            .where(*biz)
        )
        or 0.0
    )
    discovery_cost = (
        await db.scalar(
            select(func.coalesce(func.sum(ProviderUsage.cost_usd), 0.0)).where(ProviderUsage.workspace_id == ws)
        )
        or 0.0
    )

    trend_start = start_day - timedelta(days=days - 1)
    day_col = func.date(Business.created_at)
    trend_rows = dict(
        (
            await db.execute(
                select(day_col, func.count()).where(*biz, Business.created_at >= trend_start).group_by(day_col)
            )
        ).all()
    )
    trend = []
    for i in range(days):
        d = (trend_start + timedelta(days=i)).date()
        trend.append({"date": d.isoformat(), "count": int(trend_rows.get(d, trend_rows.get(d.isoformat(), 0)))})

    by_country = [
        {"key": k or "—", "count": n}
        for k, n in (
            await db.execute(
                select(Business.country, func.count())
                .where(*biz)
                .group_by(Business.country)
                .order_by(func.count().desc())
                .limit(10)
            )
        ).all()
    ]
    by_industry = [
        {"key": k or "—", "count": n}
        for k, n in (
            await db.execute(
                select(Business.industry, func.count())
                .where(*biz)
                .group_by(Business.industry)
                .order_by(func.count().desc())
                .limit(10)
            )
        ).all()
    ]
    by_source = [
        {"key": k, "count": n}
        for k, n in (
            await db.execute(
                select(BusinessSource.provider_key, func.count(func.distinct(BusinessSource.business_id)))
                .join(Business, Business.id == BusinessSource.business_id)
                .where(*biz)
                .group_by(BusinessSource.provider_key)
            )
        ).all()
    ]
    bucket = case(
        (Business.latest_score < 20, "0-19"),
        (Business.latest_score < 40, "20-39"),
        (Business.latest_score < 60, "40-59"),
        (Business.latest_score < 80, "60-79"),
        else_="80-100",
    )
    dist_rows = dict(
        (
            await db.execute(
                select(bucket, func.count()).where(*biz, Business.latest_score.is_not(None)).group_by(bucket)
            )
        ).all()
    )
    distribution = [
        {"bucket": b, "count": int(dist_rows.get(b, 0))} for b in ("0-19", "20-39", "40-59", "60-79", "80-100")
    ]

    recent_leads = [
        {
            "id": str(b.id),
            "name": b.name,
            "city": b.city,
            "country": b.country,
            "score": b.latest_score,
            "priority": b.latest_priority,
            "is_demo": b.is_demo,
            "created_at": b.created_at.isoformat(),
        }
        for b in await db.scalars(select(Business).where(*biz).order_by(Business.created_at.desc()).limit(8))
    ]
    active_campaigns = [
        {"id": str(c.id), "name": c.name, "status": c.status, "stage": c.stage, "stats": c.stats, "is_demo": c.is_demo}
        for c in await db.scalars(
            select(Campaign)
            .where(*camp, Campaign.status.in_([s.value for s in ACTIVE_STATUSES] + [CampaignStatus.PAUSED.value]))
            .order_by(Campaign.updated_at.desc())
            .limit(6)
        )
    ]
    activity = [
        {
            "id": str(e.id),
            "campaign_id": str(e.campaign_id),
            "campaign": name,
            "message": e.message,
            "data": {k: v for k, v in (e.data or {}).items() if k in ("t", "p")},
            "level": e.level,
            "created_at": e.created_at.isoformat(),
        }
        for e, name in (
            await db.execute(
                select(JobEvent, Campaign.name)
                .join(Campaign, Campaign.id == JobEvent.campaign_id)
                .where(*camp)
                .order_by(JobEvent.created_at.desc())
                .limit(12)
            )
        ).all()
    ]
    # Last 30 days against the 30 before, for the trend arrows on the overview.
    month_ago, two_months_ago = now - timedelta(days=30), now - timedelta(days=60)

    new_cur, new_prev, contact_cur, contact_prev = (
        await db.execute(
            select(
                func.count().filter(Business.created_at >= month_ago),
                func.count().filter(Business.created_at >= two_months_ago, Business.created_at < month_ago),
                func.count().filter(Business.created_at >= month_ago, Business.contact_count > 0),
                func.count().filter(
                    Business.created_at >= two_months_ago, Business.created_at < month_ago, Business.contact_count > 0
                ),
            ).where(*biz)
        )
    ).one()
    qual_cur, qual_prev = (
        await db.execute(
            select(
                func.count(func.distinct(CampaignLead.business_id)).filter(CampaignLead.created_at >= month_ago),
                func.count(func.distinct(CampaignLead.business_id)).filter(
                    CampaignLead.created_at >= two_months_ago, CampaignLead.created_at < month_ago
                ),
            )
            .join(Business, Business.id == CampaignLead.business_id)
            .where(*biz, CampaignLead.qualified.is_(True))
        )
    ).one()

    def charged(*cond):  # noqa: ANN001, ANN202
        return func.coalesce(func.sum(-CreditTransaction.delta).filter(*cond), 0)

    credits_cur, credits_prev = (
        await db.execute(
            select(
                charged(CreditTransaction.created_at >= month_ago),
                charged(CreditTransaction.created_at >= two_months_ago, CreditTransaction.created_at < month_ago),
            ).where(CreditTransaction.workspace_id == ws, CreditTransaction.kind == CreditKind.CAMPAIGN_CHARGE)
        )
    ).one()

    pipeline_counts = dict(
        (await db.execute(select(Business.crm_status, func.count()).where(*biz).group_by(Business.crm_status))).all()
    )
    pipeline = {k.value: int(pipeline_counts.get(k.value, 0)) for k in CrmStatus}
    reached = sum(pipeline[k.value] for k in REACHED)

    # "Contact them today": the best-scored leads nobody has reached yet that have a usable phone or WhatsApp.
    usable = [
        BusinessContact.type.in_([ContactType.PHONE, ContactType.WHATSAPP]),
        BusinessContact.is_suppressed.is_(False),
        BusinessContact.verification_status != VerificationStatus.INVALID,
    ]
    top = list(
        await db.scalars(
            select(Business)
            .where(
                *biz,
                Business.crm_status.in_([k.value for k in TO_CONTACT]),
                Business.id.in_(select(BusinessContact.business_id).where(*usable)),
            )
            .order_by(Business.latest_score.desc().nulls_last(), Business.created_at.desc())
            .limit(5)
        )
    )
    channels: dict = {}
    if top:
        for c in await db.scalars(
            select(BusinessContact)
            .where(BusinessContact.business_id.in_([b.id for b in top]), *usable)
            .order_by(BusinessContact.confidence.desc())
        ):
            channels.setdefault(c.business_id, {}).setdefault(c.type, c.value)
    # The latest ready first message per lead, so "Open WhatsApp" opens with it typed in.
    messages: dict = {}
    if top:
        for d in await db.scalars(
            select(OutreachDraft)
            .where(OutreachDraft.business_id.in_([b.id for b in top]), OutreachDraft.whatsapp_message != "")
            .order_by(OutreachDraft.created_at.desc())
        ):
            messages.setdefault(d.business_id, d.whatsapp_message)
    next_actions = [
        {
            "id": str(b.id),
            "name": b.name,
            "city": b.city,
            "country": b.country,
            "industry": b.industry,
            "score": b.latest_score,
            "priority": b.latest_priority,
            "crm_status": b.crm_status,
            "whatsapp": channels.get(b.id, {}).get(ContactType.WHATSAPP),
            "phone": channels.get(b.id, {}).get(ContactType.PHONE),
            "whatsapp_message": messages.get(b.id),
        }
        for b in top
    ]

    profile = await db.scalar(select(WorkspaceProfile).where(WorkspaceProfile.workspace_id == ws))
    telegram_linked = await db.scalar(
        select(func.count())
        .select_from(TelegramAccount)
        .where(TelegramAccount.workspace_id == ws, TelegramAccount.status == TelegramLinkStatus.APPROVED)
    )
    real_campaigns = await db.scalar(
        select(func.count())
        .select_from(Campaign)
        .where(Campaign.workspace_id == ws, Campaign.deleted_at.is_(None), Campaign.is_demo.is_(False))
    )
    checklist = {
        "email_verified": p.user.email_verified_at is not None,
        "profile": bool(profile and (profile.onboarding_completed_at or profile.description or profile.offerings)),
        "telegram": bool(telegram_linked),
        "campaign": bool(real_campaigns),
        "contacted": reached > 0,
    }

    totals = {
        "businesses": total,
        "qualified_leads": qualified,
        "with_contact": with_contact,
        "with_verified_contact": verified,
        "average_score": round(float(avg_score), 1) if avg_score else None,
        "active_campaigns": active,
        "completed_campaigns": completed,
        "failed_campaigns": status_counts.get(CampaignStatus.FAILED, 0),
        "today": today,
        "week": week,
        "month": month,
        "conversion_rate": round(qualified / total * 100, 1) if total else None,
        "reached": reached,
    }
    # Provider costs and source names are the platform's business, not the customer's.
    if p.user.is_superuser:
        totals["ai_cost_usd"] = round(float(ai_cost), 4)
        totals["discovery_cost_usd"] = round(float(discovery_cost), 4)

    return {
        "totals": totals,
        "period": {
            "new": {"current": new_cur, "previous": new_prev},
            "with_contact": {"current": contact_cur, "previous": contact_prev},
            "qualified": {"current": qual_cur, "previous": qual_prev},
            "credits_used": {"current": int(credits_cur), "previous": int(credits_prev)},
        },
        "pipeline": pipeline,
        "next_actions": next_actions,
        "checklist": checklist,
        "trend": trend,
        "by_country": by_country,
        "by_industry": by_industry,
        "by_source": by_source if p.user.is_superuser else [],
        "score_distribution": distribution,
        "recent_leads": recent_leads,
        "active_campaigns": active_campaigns,
        "recent_activity": activity,
    }
