"""Platform admin operations: the activity log of the whole platform, searches that failed or stopped moving,
CSV exports of users and payments, and viewing a customer's account read-only for support.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import Response as RawResponse
from pydantic import BaseModel
from sqlalchemy import func, or_, select

from app.api.deps import ADMIN_SESSION_COOKIE, DB, SESSION_COOKIE, SuperPrincipal, audit
from app.api.v1.admin_users import _briefs, user_filters
from app.api.v1.exports import _disposition, _filename
from app.api.v1.telegram import link_states
from app.core.config import get_settings
from app.core.errors import Conflict, NotFound
from app.core.security import create_access_token
from app.models import AuditLog, Campaign, CampaignRun, JobEvent, TopUpRequest, User, Workspace, WorkspaceMember
from app.models.enums import ACTIVE_STATUSES, ApprovalStatus, CampaignStatus, Role, TopUpStatus
from app.schemas.common import Page
from app.services import campaigns as svc
from app.services.exports import rows_to_csv

router = APIRouter(prefix="/admin", tags=["admin"])

STALL_MINUTES = 15  # no event and no run update for this long while "running" = stuck
FAILED_DAYS = 30
IMPERSONATION_MINUTES = 30


async def _emails(db: DB, user_ids: set[uuid.UUID]) -> dict[uuid.UUID, tuple[str, str]]:
    if not user_ids:
        return {}
    rows = await db.execute(select(User.id, User.email, User.full_name).where(User.id.in_(user_ids)))
    return {i: (e, n) for i, e, n in rows.all()}


async def _workspaces(db: DB, ids: set[uuid.UUID]) -> dict[uuid.UUID, tuple[str, str | None]]:
    """Workspace id -> (name, owner email)."""
    if not ids:
        return {}
    names = dict((await db.execute(select(Workspace.id, Workspace.name).where(Workspace.id.in_(ids)))).all())
    owners = (
        await db.execute(
            select(WorkspaceMember.workspace_id, User.email)
            .join(User, User.id == WorkspaceMember.user_id)
            .where(WorkspaceMember.workspace_id.in_(ids), WorkspaceMember.role == Role.OWNER)
            .order_by(WorkspaceMember.created_at)
        )
    ).all()
    owner: dict[uuid.UUID, str] = {}
    for wid, email in owners:
        owner.setdefault(wid, email)
    return {i: (names.get(i, ""), owner.get(i)) for i in ids}


# ---------------------------------------------------------------- activity log


class AuditRow(BaseModel):
    id: uuid.UUID
    created_at: datetime
    action: str
    entity_type: str | None
    entity_id: str | None
    data: dict
    ip: str | None
    via: str
    user_id: uuid.UUID | None
    user_email: str | None
    user_name: str | None
    workspace_id: uuid.UUID | None
    workspace_name: str | None


@router.get("/audit-logs", response_model=Page[AuditRow])
async def audit_logs(
    p: SuperPrincipal,
    db: DB,
    action: str | None = Query(None, max_length=80),
    q: str | None = Query(None, max_length=200),
    workspace_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> Page[AuditRow]:
    where = []
    if action:
        where.append(AuditLog.action == action)
    if workspace_id:
        where.append(AuditLog.workspace_id == workspace_id)
    if user_id:
        where.append(AuditLog.user_id == user_id)
    if q:
        like = f"%{q.strip()}%"
        where.append(
            or_(
                AuditLog.user_id.in_(select(User.id).where(or_(User.email.ilike(like), User.full_name.ilike(like)))),
                AuditLog.workspace_id.in_(select(Workspace.id).where(Workspace.name.ilike(like))),
            )
        )
    total = await db.scalar(select(func.count()).select_from(AuditLog).where(*where))
    rows = (
        await db.scalars(
            select(AuditLog)
            .where(*where)
            .order_by(AuditLog.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    users = await _emails(db, {a.user_id for a in rows if a.user_id})
    workspaces = await _workspaces(db, {a.workspace_id for a in rows if a.workspace_id})
    items = [
        AuditRow(
            id=a.id,
            created_at=a.created_at,
            action=a.action,
            entity_type=a.entity_type,
            entity_id=a.entity_id,
            data=a.data or {},
            ip=a.ip,
            via=a.via,
            user_id=a.user_id,
            user_email=users.get(a.user_id, (None, None))[0] if a.user_id else None,
            user_name=users.get(a.user_id, (None, None))[1] if a.user_id else None,
            workspace_id=a.workspace_id,
            workspace_name=workspaces.get(a.workspace_id, (None, None))[0] if a.workspace_id else None,
        )
        for a in rows
    ]
    return Page(items=items, total=int(total or 0), page=page, page_size=page_size)


@router.get("/audit-logs/actions", response_model=list[str])
async def audit_actions(p: SuperPrincipal, db: DB) -> list[str]:
    return list((await db.scalars(select(AuditLog.action).distinct().order_by(AuditLog.action))).all())


# ---------------------------------------------------------------- campaign health


class HealthRow(BaseModel):
    id: uuid.UUID
    name: str
    status: str
    stage: str
    origin: str
    workspace_id: uuid.UUID
    workspace_name: str
    owner_email: str | None
    run_number: int | None
    started_at: datetime | None
    last_activity_at: datetime | None
    last_error: str | None
    cost_usd: float
    stuck: bool


class HealthSummary(BaseModel):
    stuck: int
    running: int
    failed_7d: int


def _stall_cutoff() -> datetime:
    return datetime.now(UTC) - timedelta(minutes=STALL_MINUTES)


async def health_summary(db: DB) -> HealthSummary:
    live = [Campaign.deleted_at.is_(None), Campaign.is_demo.is_(False)]
    running = await db.scalar(
        select(func.count()).select_from(Campaign).where(*live, Campaign.status.in_([s.value for s in ACTIVE_STATUSES]))
    )
    failed = await db.scalar(
        select(func.count())
        .select_from(Campaign)
        .where(
            *live,
            Campaign.status == CampaignStatus.FAILED,
            Campaign.updated_at >= datetime.now(UTC) - timedelta(days=7),
        )
    )
    stuck = {c for _, c in await svc.stalled_runs(db, _stall_cutoff())}
    return HealthSummary(stuck=len(stuck), running=int(running or 0), failed_7d=int(failed or 0))


@router.get("/campaigns/health/summary", response_model=HealthSummary)
async def campaigns_health_summary(p: SuperPrincipal, db: DB) -> HealthSummary:
    return await health_summary(db)


@router.get("/campaigns/health", response_model=Page[HealthRow])
async def campaigns_health(
    p: SuperPrincipal,
    db: DB,
    kind: Literal["stuck", "failed", "running"] = "stuck",
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
) -> Page[HealthRow]:
    stuck_ids = {c for _, c in await svc.stalled_runs(db, _stall_cutoff())}
    where = [Campaign.deleted_at.is_(None)]
    if kind == "stuck":
        where.append(Campaign.id.in_(stuck_ids or [uuid.UUID(int=0)]))
    elif kind == "running":
        where += [Campaign.status.in_([s.value for s in ACTIVE_STATUSES]), Campaign.is_demo.is_(False)]
    else:
        where += [
            Campaign.status.in_([CampaignStatus.FAILED, CampaignStatus.PARTIALLY_COMPLETED]),
            Campaign.updated_at >= datetime.now(UTC) - timedelta(days=FAILED_DAYS),
            Campaign.is_demo.is_(False),
        ]
    total = await db.scalar(select(func.count()).select_from(Campaign).where(*where))
    campaigns = (
        await db.scalars(
            select(Campaign)
            .where(*where)
            .order_by(Campaign.updated_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    ids = [c.id for c in campaigns]
    runs = {
        cid: n
        for cid, n in (
            await db.execute(
                select(CampaignRun.campaign_id, func.max(CampaignRun.run_number))
                .where(CampaignRun.campaign_id.in_(ids))
                .group_by(CampaignRun.campaign_id)
            )
        ).all()
    }
    events = {
        cid: at
        for cid, at in (
            await db.execute(
                select(JobEvent.campaign_id, func.max(JobEvent.created_at))
                .where(JobEvent.campaign_id.in_(ids))
                .group_by(JobEvent.campaign_id)
            )
        ).all()
    }
    workspaces = await _workspaces(db, {c.workspace_id for c in campaigns})
    items = [
        HealthRow(
            id=c.id,
            name=c.name,
            status=c.status,
            stage=c.stage,
            origin=c.origin,
            workspace_id=c.workspace_id,
            workspace_name=workspaces.get(c.workspace_id, ("", None))[0],
            owner_email=workspaces.get(c.workspace_id, ("", None))[1],
            run_number=runs.get(c.id),
            started_at=c.started_at,
            last_activity_at=events.get(c.id) or c.updated_at,
            last_error=c.last_error,
            cost_usd=round(float(c.cost_discovery or 0) + float(c.cost_ai or 0), 4),
            stuck=c.id in stuck_ids,
        )
        for c in campaigns
    ]
    return Page(items=items, total=int(total or 0), page=page, page_size=page_size)


async def _campaign(db: DB, campaign_id: uuid.UUID) -> Campaign:
    c = await db.scalar(select(Campaign).where(Campaign.id == campaign_id, Campaign.deleted_at.is_(None)))
    if c is None:
        raise NotFound("Campaign not found")
    return c


async def _audit_campaign(db: DB, p: SuperPrincipal, action: str, c: Campaign) -> None:
    await audit(db, p, action, "campaign", c.id, {"name": c.name, "workspace_id": str(c.workspace_id)})


@router.post("/campaigns/{campaign_id}/requeue")
async def requeue_campaign(campaign_id: uuid.UUID, p: SuperPrincipal, db: DB) -> dict:
    """Hand a stuck run to a worker again; it resumes from its checkpoint (as the periodic recovery does)."""
    c = await _campaign(db, campaign_id)
    run = await svc.latest_run(db, c.id)
    if c.status not in ACTIVE_STATUSES or run is None or run.finished_at is not None:
        raise Conflict("Only a running campaign can be re-queued")
    run.celery_task_id = svc.dispatch_run(c.id, run.id)
    await _audit_campaign(db, p, "admin.campaign_requeued", c)
    await db.commit()
    return {"status": c.status, "run_number": run.run_number}


@router.post("/campaigns/{campaign_id}/retry")
async def retry_campaign(campaign_id: uuid.UUID, p: SuperPrincipal, db: DB) -> dict:
    c = await _campaign(db, campaign_id)
    run = await svc.retry_failures(db, c)
    await _audit_campaign(db, p, "admin.campaign_retried", c)
    await db.commit()
    return {"status": c.status, "run_number": run.run_number}


@router.post("/campaigns/{campaign_id}/cancel")
async def cancel_campaign(campaign_id: uuid.UUID, p: SuperPrincipal, db: DB) -> dict:
    c = await _campaign(db, campaign_id)
    await svc.cancel_campaign(db, c)
    await _audit_campaign(db, p, "admin.campaign_cancelled", c)
    await db.commit()
    return {"status": c.status}


# ---------------------------------------------------------------- CSV exports


def _csv(prefix: str, header: list[str], rows: list[list]) -> RawResponse:
    return RawResponse(
        rows_to_csv(header, rows),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": _disposition(_filename(prefix, "csv"))},
    )


def _iso(d: datetime | None) -> str:
    return d.isoformat(timespec="minutes") if d else ""


USER_COLUMNS = [
    "name", "email", "phone", "nationality", "approval", "email_confirmed", "signed_up", "last_sign_in",
    "workspace", "role", "balance", "plan", "telegram", "telegram_username", "paid",
]  # fmt: skip


@router.get("/exports/users.csv")
async def export_users(
    p: SuperPrincipal,
    db: DB,
    q: str | None = Query(None, max_length=200),
    status: ApprovalStatus | None = None,
    suspicious: bool = False,
    nationality: str | None = Query(None, pattern="^[A-Za-z]{2}$"),
    telegram: bool | None = None,
) -> RawResponse:
    users = (
        await db.scalars(
            select(User)
            .where(*user_filters(q, status, suspicious, nationality, telegram))
            .order_by(User.created_at.desc())
        )
    ).all()
    ids = [u.id for u in users]
    briefs, tg = await _briefs(db, ids), await link_states(db, ids)
    ws_ids = {b[0].id for b in briefs.values() if b}
    paid: dict[uuid.UUID, dict[str, float]] = {}
    if ws_ids:
        for wid, cur, total in (
            await db.execute(
                select(TopUpRequest.workspace_id, TopUpRequest.currency, func.sum(TopUpRequest.amount))
                .where(TopUpRequest.workspace_id.in_(ws_ids), TopUpRequest.status == TopUpStatus.APPROVED)
                .group_by(TopUpRequest.workspace_id, TopUpRequest.currency)
            )
        ).all():
            paid.setdefault(wid, {})[cur] = float(total or 0)
    rows = []
    for u in users:
        w = (briefs.get(u.id) or [None])[0]
        state, username = tg.get(u.id, ("none", None))
        plan = ""
        if w:
            plan = (
                "suspended" if w.suspended_at else "exempt" if w.billing_exempt else "trial" if w.on_trial
                else "paid" if w.trial_ends_at else "no_trial"
            )  # fmt: skip
        rows.append(
            [
                u.full_name,
                u.email,
                u.phone or "",
                u.nationality or "",
                u.approval_status,
                "yes" if u.email_verified_at else "no",
                _iso(u.created_at),
                _iso(u.last_login_at),
                w.name if w else "",
                w.role.value if w else "",
                ("" if not w else "unlimited" if w.billing_exempt else w.balance),
                plan,
                state,
                username or "",
                " + ".join(f"{a:.2f} {c}" for c, a in paid.get(w.id, {}).items()) if w else "",
            ]  # fmt: skip
        )
    await audit(db, p, "admin.users_exported", data={"count": len(rows)})
    await db.commit()
    return _csv("rasd-users", USER_COLUMNS, rows)


PAYMENT_COLUMNS = [
    "date", "workspace", "owner_email", "requested_by", "credits", "amount", "currency", "method", "reference",
    "status", "reason", "reviewed_at",
]  # fmt: skip


@router.get("/exports/payments.csv")
async def export_payments(
    p: SuperPrincipal,
    db: DB,
    status: TopUpStatus | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> RawResponse:
    where = []
    if status:
        where.append(TopUpRequest.status == status)
    if since:
        where.append(TopUpRequest.created_at >= since)
    if until:
        where.append(TopUpRequest.created_at < until)
    topups = (await db.scalars(select(TopUpRequest).where(*where).order_by(TopUpRequest.created_at.desc()))).all()
    workspaces = await _workspaces(db, {t.workspace_id for t in topups})
    requesters = await _emails(db, {t.created_by for t in topups if t.created_by})
    rows = [
        [
            _iso(t.created_at),
            workspaces.get(t.workspace_id, ("", None))[0],
            workspaces.get(t.workspace_id, ("", None))[1] or "",
            requesters.get(t.created_by, ("", ""))[0] if t.created_by else "",
            t.credits,
            f"{t.amount:.2f}",
            t.currency,
            t.method,
            t.reference or "",
            t.status,
            t.reason or "",
            _iso(t.reviewed_at),
        ]  # fmt: skip
        for t in topups
    ]
    await audit(db, p, "admin.payments_exported", data={"count": len(rows)})
    await db.commit()
    return _csv("rasd-payments", PAYMENT_COLUMNS, rows)


# ---------------------------------------------------------------- view a customer's account (read-only)


@router.post("/users/{user_id}/impersonate")
async def impersonate(user_id: uuid.UUID, p: SuperPrincipal, request: Request, response: Response, db: DB) -> dict:
    """Swap the browser session for a 30-minute read-only one of the customer; the admin's own is kept aside."""
    if p.impersonator is not None or p.via != "web":
        raise Conflict("Start viewing an account from your own dashboard session")
    user = await db.scalar(select(User).where(User.id == user_id, User.deleted_at.is_(None)))
    if user is None:
        raise NotFound("User not found")
    if user.is_superuser:
        raise Conflict("Platform admins cannot be viewed as a customer", code="cannot_impersonate_admin")
    if not user.is_active:
        raise Conflict("This account is disabled", code="user_inactive")
    member = await db.scalar(
        select(WorkspaceMember).where(WorkspaceMember.user_id == user.id).order_by(WorkspaceMember.created_at).limit(1)
    )
    if member is None:
        raise Conflict("This user has no workspace yet", code="no_workspace")
    s = get_settings()
    response.set_cookie(
        ADMIN_SESSION_COOKIE,
        request.cookies.get(SESSION_COOKIE, ""),
        httponly=True,
        secure=s.cookie_secure,
        samesite="lax",
        domain=s.cookie_domain,
        path="/",
        max_age=s.access_token_minutes * 60,
    )
    token = create_access_token(
        user.id,
        member.workspace_id,
        minutes=IMPERSONATION_MINUTES,
        password_hash=user.password_hash,
        impersonator=p.user.id,
    )
    # Only the session is swapped: the CSRF cookie keeps its lifetime so "back to my account" still works after 30 min.
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        secure=s.cookie_secure,
        samesite="lax",
        domain=s.cookie_domain,
        path="/",
        max_age=IMPERSONATION_MINUTES * 60,
    )
    db.add(
        AuditLog(
            workspace_id=member.workspace_id,
            user_id=p.user.id,
            action="admin.impersonation_started",
            entity_type="user",
            entity_id=str(user.id),
            data={"email": user.email},
            ip=request.client.host if request.client else None,
        )
    )
    await db.commit()
    return {"user_id": str(user.id), "email": user.email, "minutes": IMPERSONATION_MINUTES}
