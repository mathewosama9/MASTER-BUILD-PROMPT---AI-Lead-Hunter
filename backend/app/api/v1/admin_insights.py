"""Platform admin dashboards (superusers only): business overview, signup funnel and per-workspace usage vs revenue.

Read-only. Revenue is what admins approved from manual top-ups; costs are what providers billed the platform.
"""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Query
from sqlalchemy import and_, func, select

from app.api.deps import DB, SuperPrincipal
from app.api.v1.admin_ops import health_summary
from app.models import (
    Business,
    Campaign,
    ContactRequest,
    CreditTransaction,
    LeadAssessment,
    OutreachDraft,
    ProviderUsage,
    Testimonial,
    TopUpRequest,
    User,
    Workspace,
    WorkspaceMember,
)
from app.models.enums import ApprovalStatus, CreditKind, Role, TestimonialSource, TestimonialStatus, TopUpStatus

router = APIRouter(prefix="/admin", tags=["admin"])


def _days(n: int) -> list[str]:
    today = datetime.now(UTC).date()
    return [(today - timedelta(days=i)).isoformat() for i in range(n - 1, -1, -1)]


@router.get("/overview")
async def overview(p: SuperPrincipal, db: DB) -> dict:
    now = datetime.now(UTC)
    d7, d30 = now - timedelta(days=7), now - timedelta(days=30)
    customer = [Workspace.deleted_at.is_(None), Workspace.billing_exempt.is_(False)]

    users_7d, users_30d, users_total = (
        await db.execute(
            select(
                func.count().filter(User.created_at >= d7),
                func.count().filter(User.created_at >= d30),
                func.count(),
            )
        )
    ).one()
    workspaces_total = await db.scalar(select(func.count()).select_from(Workspace).where(*customer)) or 0
    active_30d = (
        await db.scalar(
            select(func.count(func.distinct(Campaign.workspace_id))).where(
                Campaign.created_at >= d30, Campaign.is_demo.is_(False), Campaign.deleted_at.is_(None)
            )
        )
        or 0
    )

    approved = [TopUpRequest.status == TopUpStatus.APPROVED]
    revenue_30d = [
        {"currency": c, "amount": float(a)}
        for c, a in (
            await db.execute(
                select(TopUpRequest.currency, func.sum(TopUpRequest.amount))
                .where(*approved, TopUpRequest.reviewed_at >= d30)
                .group_by(TopUpRequest.currency)
            )
        ).all()
    ]
    revenue_total = [
        {"currency": c, "amount": float(a)}
        for c, a in (
            await db.execute(
                select(TopUpRequest.currency, func.sum(TopUpRequest.amount))
                .where(*approved)
                .group_by(TopUpRequest.currency)
            )
        ).all()
    ]
    charge = [CreditTransaction.kind == CreditKind.CAMPAIGN_CHARGE]
    credits_30d = (
        await db.scalar(
            select(func.coalesce(-func.sum(CreditTransaction.delta), 0)).where(
                *charge, CreditTransaction.created_at >= d30
            )
        )
        or 0
    )

    pending_topups = (
        await db.scalar(
            select(func.count()).select_from(TopUpRequest).where(TopUpRequest.status == TopUpStatus.PENDING)
        )
        or 0
    )
    new_contacts = (
        await db.scalar(select(func.count()).select_from(ContactRequest).where(ContactRequest.status == "new")) or 0
    )
    health = await health_summary(db)
    pending_signups = (
        await db.scalar(
            select(func.count())
            .select_from(User)
            .where(User.approval_status == ApprovalStatus.PENDING, User.deleted_at.is_(None))
        )
        or 0
    )
    pending_reviews = (
        await db.scalar(
            select(func.count()).select_from(Testimonial).where(Testimonial.status == TestimonialStatus.PENDING)
        )
        or 0
    )
    sample_reviews = (
        await db.scalar(
            select(func.count())
            .select_from(Testimonial)
            .where(Testimonial.source == TestimonialSource.SAMPLE, Testimonial.status == TestimonialStatus.APPROVED)
        )
        or 0
    )

    # Funnel over customer workspaces: signed up → owner confirmed email → ran a real search → paid.
    owner_verified = (
        select(WorkspaceMember.workspace_id)
        .join(User, User.id == WorkspaceMember.user_id)
        .where(WorkspaceMember.role == Role.OWNER, User.email_verified_at.is_not(None))
    )
    ran = select(Campaign.workspace_id).where(Campaign.is_demo.is_(False), Campaign.deleted_at.is_(None))
    paid = select(CreditTransaction.workspace_id).where(CreditTransaction.kind == CreditKind.PURCHASE)
    signed, verified, searched, bought = (
        await db.execute(
            select(
                func.count(),
                func.count().filter(Workspace.id.in_(owner_verified)),
                func.count().filter(Workspace.id.in_(ran)),
                func.count().filter(Workspace.id.in_(paid)),
            ).where(*customer)
        )
    ).one()

    days = _days(30)
    day = func.date(User.created_at)
    signups = dict((await db.execute(select(day, func.count()).where(User.created_at >= d30).group_by(day))).all())
    cday = func.date(CreditTransaction.created_at)
    used = dict(
        (
            await db.execute(
                select(cday, func.coalesce(-func.sum(CreditTransaction.delta), 0))
                .where(*charge, CreditTransaction.created_at >= d30)
                .group_by(cday)
            )
        ).all()
    )

    def at(m: dict, d: str) -> int:
        return int(next((v for k, v in m.items() if str(k) == d), 0))

    month = func.to_char(TopUpRequest.reviewed_at, "YYYY-MM")
    monthly = [
        {"month": m, "currency": c, "amount": float(a)}
        for m, c, a in (
            await db.execute(
                select(month, TopUpRequest.currency, func.sum(TopUpRequest.amount))
                .where(*approved, TopUpRequest.reviewed_at >= now - timedelta(days=186))
                .group_by(month, TopUpRequest.currency)
                .order_by(month)
            )
        ).all()
    ]

    return {
        "users": {"last_7d": users_7d, "last_30d": users_30d, "total": users_total},
        "workspaces": {"total": workspaces_total, "active_30d": active_30d},
        "revenue": {"last_30d": revenue_30d, "total": revenue_total, "monthly": monthly},
        "credits_used_30d": int(credits_30d),
        "attention": {
            "pending_topups": pending_topups,
            "pending_signups": pending_signups,
            "stuck_campaigns": health.stuck,
            "failed_campaigns_7d": health.failed_7d,
            "new_contacts": new_contacts,
            "pending_reviews": pending_reviews,
            "sample_reviews": sample_reviews,
        },
        "funnel": {"signed_up": signed, "verified": verified, "first_search": searched, "paid": bought},
        "daily": [{"date": d, "signups": at(signups, d), "credits_used": at(used, d)} for d in days],
    }


@router.get("/usage")
async def usage(p: SuperPrincipal, db: DB, days: int = Query(30, ge=1, le=365)) -> list[dict]:
    """Per workspace over the period: credits charged, revenue approved and what providers cost the platform."""
    since = datetime.now(UTC) - timedelta(days=days)
    credits = (
        select(CreditTransaction.workspace_id.label("ws"), (-func.sum(CreditTransaction.delta)).label("credits"))
        .where(CreditTransaction.kind == CreditKind.CAMPAIGN_CHARGE, CreditTransaction.created_at >= since)
        .group_by(CreditTransaction.workspace_id)
        .subquery()
    )
    discovery = (
        select(ProviderUsage.workspace_id.label("ws"), func.sum(ProviderUsage.cost_usd).label("cost"))
        .where(ProviderUsage.created_at >= since)
        .group_by(ProviderUsage.workspace_id)
        .subquery()
    )

    def ai_cost(model):  # noqa: ANN001, ANN202
        return (
            select(Business.workspace_id.label("ws"), func.sum(model.cost_usd).label("cost"))
            .join(Business, Business.id == model.business_id)
            .where(model.created_at >= since)
            .group_by(Business.workspace_id)
            .subquery()
        )

    analysis, drafts = ai_cost(LeadAssessment), ai_cost(OutreachDraft)
    revenue = (
        select(
            TopUpRequest.workspace_id.label("ws"),
            func.sum(TopUpRequest.amount).label("amount"),
            func.max(TopUpRequest.currency).label("currency"),
        )
        .where(TopUpRequest.status == TopUpStatus.APPROVED, TopUpRequest.reviewed_at >= since)
        .group_by(TopUpRequest.workspace_id)
        .subquery()
    )
    rows = (
        await db.execute(
            select(
                Workspace.id,
                Workspace.name,
                Workspace.billing_exempt,
                func.coalesce(credits.c.credits, 0),
                func.coalesce(discovery.c.cost, 0.0),
                func.coalesce(analysis.c.cost, 0.0) + func.coalesce(drafts.c.cost, 0.0),
                func.coalesce(revenue.c.amount, 0),
                revenue.c.currency,
            )
            .outerjoin(credits, credits.c.ws == Workspace.id)
            .outerjoin(discovery, discovery.c.ws == Workspace.id)
            .outerjoin(analysis, analysis.c.ws == Workspace.id)
            .outerjoin(drafts, drafts.c.ws == Workspace.id)
            .outerjoin(revenue, revenue.c.ws == Workspace.id)
            .where(
                Workspace.deleted_at.is_(None),
                and_(
                    func.coalesce(credits.c.credits, 0)
                    + func.coalesce(discovery.c.cost, 0)
                    + func.coalesce(analysis.c.cost, 0)
                    + func.coalesce(drafts.c.cost, 0)
                    + func.coalesce(revenue.c.amount, 0)
                    > 0
                ),
            )
            .order_by(func.coalesce(credits.c.credits, 0).desc())
            .limit(100)
        )
    ).all()
    return [
        {
            "workspace_id": str(wid),
            "name": name,
            "billing_exempt": exempt,
            "credits_used": int(cr),
            "discovery_cost_usd": round(float(dc), 4),
            "ai_cost_usd": round(float(ac), 4),
            "revenue": float(rv),
            "currency": cur,
        }
        for wid, name, exempt, cr, dc, ac, rv, cur in rows
    ]
