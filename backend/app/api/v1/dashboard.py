from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Query
from sqlalchemy import case, func, select

from app.api.deps import DB, CurrentPrincipal
from app.models import (
    Business,
    BusinessSource,
    Campaign,
    CampaignLead,
    JobEvent,
    LeadAssessment,
    ProviderUsage,
)
from app.models.enums import ACTIVE_STATUSES, CampaignStatus

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
    return {
        "totals": {
            "businesses": total,
            "qualified_leads": qualified,
            "with_contact": with_contact,
            "with_verified_contact": verified,
            "average_score": round(float(avg_score), 1) if avg_score else None,
            "active_campaigns": active,
            "completed_campaigns": completed,
            "failed_campaigns": status_counts.get(CampaignStatus.FAILED, 0),
            "ai_cost_usd": round(float(ai_cost), 4),
            "discovery_cost_usd": round(float(discovery_cost), 4),
            "today": today,
            "week": week,
            "month": month,
            "conversion_rate": round(qualified / total * 100, 1) if total else None,
        },
        "trend": trend,
        "by_country": by_country,
        "by_industry": by_industry,
        "by_source": by_source,
        "score_distribution": distribution,
        "recent_leads": recent_leads,
        "active_campaigns": active_campaigns,
        "recent_activity": activity,
    }
