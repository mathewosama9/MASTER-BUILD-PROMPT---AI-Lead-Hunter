"""Platform admin: every user on the platform, their subscription and payments, signup review and possible
duplicate accounts (services/signup_review.py). The Telegram bot uses the same endpoints for its Approve / Reject
buttons, as the admin's linked account.
"""

import re
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Query
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import exists, func, select, union
from sqlalchemy.exc import IntegrityError

from app.api.deps import DB, Principal, SuperPrincipal, audit
from app.api.v1.telegram import link_states
from app.core.countries import ISO_COUNTRIES
from app.core.errors import AppError, Conflict, Forbidden, NotFound
from app.models import (
    AccountSignal,
    AuditLog,
    Campaign,
    CreditPackage,
    CreditTransaction,
    TelegramAccount,
    TopUpRequest,
    User,
    Workspace,
    WorkspaceMember,
)
from app.models.enums import (
    ApprovalStatus,
    CreditKind,
    PaymentMethod,
    Role,
    SignalKind,
    TelegramLinkStatus,
    TopUpStatus,
)
from app.schemas.auth import clean_phone
from app.schemas.billing import TopUpOut, TransactionOut
from app.schemas.common import Message, Page
from app.services import accounts
from app.services import credits as credit_svc
from app.services import signup_review as review
from app.services.notify import events as notify_events

router = APIRouter(prefix="/admin/users", tags=["admin"])


class WorkspaceBrief(BaseModel):
    id: uuid.UUID
    name: str
    role: Role
    balance: int
    billing_exempt: bool
    trial_ends_at: datetime | None
    on_trial: bool
    suspended_at: datetime | None


class AdminUserRow(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str
    phone: str | None
    nationality: str | None
    approval_status: ApprovalStatus
    is_active: bool
    is_superuser: bool
    email_verified_at: datetime | None
    created_at: datetime
    last_login_at: datetime | None
    last_seen_at: datetime | None = None
    signup_ip: str | None
    matches: int
    strong_matches: int
    workspace: WorkspaceBrief | None
    telegram_status: str = "none"  # linked | pending | none
    telegram_username: str | None = None


async def _briefs(db: DB, user_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[WorkspaceBrief]]:
    if not user_ids:
        return {}
    purchased = (
        exists()
        .where(CreditTransaction.workspace_id == Workspace.id, CreditTransaction.kind == CreditKind.PURCHASE)
        .correlate(Workspace)
    )
    rows = (
        await db.execute(
            select(WorkspaceMember.user_id, WorkspaceMember.role, Workspace, purchased)
            .join(Workspace, Workspace.id == WorkspaceMember.workspace_id)
            .where(WorkspaceMember.user_id.in_(user_ids), Workspace.deleted_at.is_(None))
            .order_by(WorkspaceMember.created_at)
        )
    ).all()
    out: dict[uuid.UUID, list[WorkspaceBrief]] = {}
    for uid, role, ws, paid in rows:
        out.setdefault(uid, []).append(
            WorkspaceBrief(
                id=ws.id,
                name=ws.name,
                role=Role(role),
                balance=ws.credit_balance,
                billing_exempt=ws.billing_exempt,
                trial_ends_at=ws.trial_ends_at,
                on_trial=ws.trial_ends_at is not None and not paid,
                suspended_at=ws.suspended_at,
            )
        )
    return out


def _row(
    u: User, matches: int, strong: int, briefs: list[WorkspaceBrief], tg: tuple[str, str | None] = ("none", None)
) -> AdminUserRow:
    return AdminUserRow(
        id=u.id,
        email=u.email,
        full_name=u.full_name,
        phone=u.phone,
        nationality=u.nationality,
        approval_status=ApprovalStatus(u.approval_status),
        is_active=u.is_active,
        is_superuser=u.is_superuser,
        email_verified_at=u.email_verified_at,
        created_at=u.created_at,
        last_login_at=u.last_login_at,
        last_seen_at=u.last_seen_at,
        signup_ip=u.signup_ip,
        matches=int(matches or 0),
        strong_matches=int(strong or 0),
        workspace=briefs[0] if briefs else None,
        telegram_status=tg[0],
        telegram_username=tg[1],
    )


def _telegram_linked():  # noqa: ANN202
    return select(TelegramAccount.user_id).where(TelegramAccount.status == TelegramLinkStatus.APPROVED)


def user_filters(
    q: str | None = None,
    status: ApprovalStatus | None = None,
    suspicious: bool = False,
    nationality: str | None = None,
    telegram: bool | None = None,
) -> list:
    """WHERE clauses of the users list; the CSV export (admin_ops.py) applies the same ones."""
    where = [User.deleted_at.is_(None)]
    if status:
        where.append(User.approval_status == status)
    if suspicious:
        where.append(User.dup_matches > 0)  # stored count, partial index
    if nationality:
        where.append(User.nationality == nationality.upper())
    if telegram is not None:
        where.append(User.id.in_(_telegram_linked()) if telegram else User.id.not_in(_telegram_linked()))
    if q and q.strip():
        # %, _ and \ typed by the admin are literal. A UNION of one subquery per column lets each use its own
        # trigram index (migration 0018); an OR across them would fall back to scanning the whole table.
        like = "%" + re.sub(r"([\\%_])", r"\\\1", q.strip()) + "%"
        matching = union(
            select(User.id).where(User.email.ilike(like, escape="\\")),
            select(User.id).where(User.full_name.ilike(like, escape="\\")),
            select(User.id).where(User.phone.ilike(like, escape="\\")),
            select(WorkspaceMember.user_id)
            .join(Workspace, Workspace.id == WorkspaceMember.workspace_id)
            .where(Workspace.name.ilike(like, escape="\\")),
        )
        where.append(User.id.in_(matching))
    return where


@router.get("", response_model=Page[AdminUserRow])
async def list_users(
    p: SuperPrincipal,
    db: DB,
    q: str | None = Query(None, max_length=200),
    status: ApprovalStatus | None = None,
    suspicious: bool = False,
    nationality: str | None = Query(None, pattern="^[A-Za-z]{2}$"),
    telegram: bool | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
) -> Page[AdminUserRow]:
    where = user_filters(q, status, suspicious, nationality, telegram)
    total = await db.scalar(select(func.count()).select_from(User).where(*where))
    users = (
        await db.scalars(
            select(User)
            .where(*where)
            .order_by(User.created_at.desc(), User.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    ids = [u.id for u in users]
    briefs, tg = await _briefs(db, ids), await link_states(db, ids)
    items = [_row(u, u.dup_matches, u.dup_strong, briefs.get(u.id, []), tg.get(u.id, ("none", None))) for u in users]
    return Page(items=items, total=int(total or 0), page=page, page_size=page_size)


class UsersSummary(BaseModel):
    total: int
    pending: int
    suspicious: int
    suspicious_pending: int
    rejected: int
    new_7d: int
    telegram_linked: int


@router.get("/summary", response_model=UsersSummary)
async def users_summary(p: SuperPrincipal, db: DB) -> UsersSummary:
    # One pass over the table with FILTERed counts instead of a query per number.
    pending = User.approval_status == ApprovalStatus.PENDING
    flagged = User.dup_matches > 0
    row = (
        await db.execute(
            select(
                func.count(),
                func.count().filter(pending),
                func.count().filter(flagged),
                func.count().filter(flagged, pending),
                func.count().filter(User.approval_status == ApprovalStatus.REJECTED),
                func.count().filter(User.created_at >= datetime.now(UTC) - timedelta(days=7)),
                func.count().filter(User.id.in_(_telegram_linked())),
            ).where(User.deleted_at.is_(None))
        )
    ).one()
    keys = ("total", "pending", "suspicious", "suspicious_pending", "rejected", "new_7d", "telegram_linked")
    return UsersSummary(**{k: int(v or 0) for k, v in zip(keys, row, strict=True)})


class WorkspaceDetail(WorkspaceBrief):
    campaigns: int
    credits_used: int
    credits_purchased: int
    # Approved payments, summed per currency, e.g. {"USD": "120.00"}
    paid: dict[str, Decimal]


class MatchOut(BaseModel):
    user_id: uuid.UUID
    email: str
    full_name: str
    approval_status: str
    is_active: bool
    created_at: datetime
    kinds: list[str]
    values: dict[str, str]
    strong: bool


class LoginOut(BaseModel):
    at: datetime
    action: str
    ip: str | None
    via: str


class AdminTopUpRow(TopUpOut):
    workspace_id: uuid.UUID


class AdminTransactionRow(TransactionOut):
    workspace_id: uuid.UUID


class DeviceOut(BaseModel):
    """One browser the user signed in from (the device cookie), with who else used it."""

    id: str  # first characters of the device id, enough to tell devices apart
    user_agent: str | None
    ip: str | None
    first_seen: datetime
    last_seen: datetime | None
    shared_with: int


class AdminUserDetail(AdminUserRow):
    locale: str
    last_seen_ip: str | None
    admin_notes: str | None
    suspicion: str  # strong | weak | none
    devices: list[DeviceOut]
    reviewed_at: datetime | None
    reviewed_by: str | None
    review_note: str | None
    workspaces: list[WorkspaceDetail]
    duplicates: list[MatchOut]
    topups: list[AdminTopUpRow]
    transactions: list[AdminTransactionRow]
    logins: list[LoginOut]


async def _workspace_details(db: DB, briefs: list[WorkspaceBrief]) -> list[WorkspaceDetail]:
    out = []
    for b in briefs:
        campaigns = await db.scalar(
            select(func.count(Campaign.id)).where(Campaign.workspace_id == b.id, Campaign.deleted_at.is_(None))
        )
        sums = dict(
            (
                await db.execute(
                    select(CreditTransaction.kind, func.sum(CreditTransaction.delta))
                    .where(CreditTransaction.workspace_id == b.id)
                    .group_by(CreditTransaction.kind)
                )
            ).all()
        )
        paid = dict(
            (
                await db.execute(
                    select(TopUpRequest.currency, func.sum(TopUpRequest.amount))
                    .where(TopUpRequest.workspace_id == b.id, TopUpRequest.status == TopUpStatus.APPROVED)
                    .group_by(TopUpRequest.currency)
                )
            ).all()
        )
        out.append(
            WorkspaceDetail(
                **b.model_dump(),
                campaigns=int(campaigns or 0),
                credits_used=-int(sums.get(CreditKind.CAMPAIGN_CHARGE) or 0),
                credits_purchased=int(sums.get(CreditKind.PURCHASE) or 0),
                paid=paid,
            )
        )
    return out


async def _detail(db: DB, user_id: uuid.UUID) -> AdminUserDetail:
    user = await db.scalar(select(User).where(User.id == user_id, User.deleted_at.is_(None)))
    if user is None:
        raise NotFound("User not found")
    briefs = (await _briefs(db, [user.id])).get(user.id, [])
    ws_ids = [b.id for b in briefs]
    topups = (
        await db.scalars(
            select(TopUpRequest)
            .where(TopUpRequest.workspace_id.in_(ws_ids))
            .order_by(TopUpRequest.created_at.desc())
            .limit(50)
        )
    ).all()
    txs = (
        await db.scalars(
            select(CreditTransaction)
            .where(CreditTransaction.workspace_id.in_(ws_ids))
            .order_by(CreditTransaction.created_at.desc())
            .limit(50)
        )
    ).all()
    logins = (
        await db.scalars(
            select(AuditLog)
            .where(AuditLog.user_id == user.id, AuditLog.action.in_(["auth.login", "auth.registered"]))
            .order_by(AuditLog.created_at.desc())
            .limit(20)
        )
    ).all()
    devices = (
        await db.scalars(
            select(AccountSignal)
            .where(AccountSignal.user_id == user.id, AccountSignal.kind == SignalKind.DEVICE)
            .order_by(AccountSignal.last_seen_at.desc().nulls_last())
            .limit(review.KEEP[SignalKind.DEVICE])
        )
    ).all()
    reviewer = await db.scalar(select(User.email).where(User.id == user.reviewed_by)) if user.reviewed_by else None
    found = await review.matches(db, user.id)
    strong = sum(1 for x in found if x.strong)
    if (user.dup_matches, user.dup_strong) != (len(found), strong):  # self-heal a stale stored count
        await review.store_counts(db, user.id, found)
        await db.commit()
    shared = dict(
        (
            await db.execute(
                select(AccountSignal.value, func.count(func.distinct(AccountSignal.user_id)))
                .where(
                    AccountSignal.kind == SignalKind.DEVICE,
                    AccountSignal.value.in_([x.value for x in devices]),
                    AccountSignal.user_id != user.id,
                )
                .group_by(AccountSignal.value)
            )
        ).all()
    )
    return AdminUserDetail(
        **_row(
            user, len(found), strong, briefs, (await link_states(db, [user.id])).get(user.id, ("none", None))
        ).model_dump(),
        locale=user.locale,
        last_seen_ip=user.last_seen_ip,
        admin_notes=user.admin_notes,
        suspicion="strong" if any(x.strong for x in found) else "weak" if found else "none",
        devices=[
            DeviceOut(
                id=x.value[:8],
                user_agent=x.user_agent,
                ip=x.ip,
                first_seen=x.created_at,
                last_seen=x.last_seen_at,
                shared_with=int(shared.get(x.value, 0)),
            )
            for x in sorted(devices, key=lambda x: x.last_seen_at or x.created_at, reverse=True)
        ],
        reviewed_at=user.reviewed_at,
        reviewed_by=reviewer,
        review_note=user.review_note,
        workspaces=await _workspace_details(db, briefs),
        duplicates=[MatchOut(**vars(x), strong=x.strong) for x in found],
        topups=[AdminTopUpRow(**TopUpOut.model_validate(t).model_dump(), workspace_id=t.workspace_id) for t in topups],
        transactions=[
            AdminTransactionRow(**TransactionOut.model_validate(t).model_dump(), workspace_id=t.workspace_id)
            for t in txs
        ],
        logins=[LoginOut(at=a.created_at, action=a.action, ip=a.ip, via=a.via) for a in logins],
    )


@router.get("/{user_id}", response_model=AdminUserDetail)
async def get_user(user_id: uuid.UUID, p: SuperPrincipal, db: DB) -> AdminUserDetail:
    return await _detail(db, user_id)


def _web_only(p: Principal) -> None:
    """Credits, identity and password actions need the dashboard session. The bot's service token (which can
    approve and reject signups) must not also be able to move money or take over an account."""
    if p.via == "telegram":
        raise Forbidden("Use the dashboard for this action", code="dashboard_only")


async def _locked(db: DB, user_id: uuid.UUID) -> User:
    # Row lock: the dashboard and a Telegram button pressed at once cannot both act (or start the trial twice).
    user = await db.scalar(select(User).where(User.id == user_id, User.deleted_at.is_(None)).with_for_update())
    if user is None:
        raise NotFound("User not found")
    return user


@router.post("/{user_id}/approve", response_model=AdminUserDetail)
async def approve_user(user_id: uuid.UUID, p: SuperPrincipal, db: DB) -> AdminUserDetail:
    user = await _locked(db, user_id)
    if not await review.approve(db, user, p.user.id):
        raise Conflict("This account is already approved", code="already_reviewed")
    await audit(db, p, "admin.user_approved", "user", user.id, {"email": user.email})
    await db.commit()
    return await _detail(db, user_id)


class RejectUserIn(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


@router.post("/{user_id}/reject", response_model=AdminUserDetail)
async def reject_user(user_id: uuid.UUID, body: RejectUserIn, p: SuperPrincipal, db: DB) -> AdminUserDetail:
    user = await _locked(db, user_id)
    if user.id == p.user.id or user.is_superuser:
        raise Conflict("Platform admins cannot be rejected", code="cannot_reject_admin")
    if not await review.reject(db, user, p.user.id, body.reason.strip()):
        raise Conflict("This account is already rejected", code="already_reviewed")
    await audit(db, p, "admin.user_rejected", "user", user.id, {"email": user.email, "reason": user.review_note})
    await db.commit()
    return await _detail(db, user_id)


# ---------------------------------------------------------------- editing a user


class UserPatch(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=200)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=32)
    nationality: str | None = Field(default=None, pattern="^[A-Za-z]{2}$")
    locale: Literal["ar", "en"] | None = None
    is_active: bool | None = None
    email_verified: bool | None = None
    admin_notes: str | None = Field(default=None, max_length=5000)

    @field_validator("full_name", mode="before")
    @classmethod
    def _name(cls, v: object) -> object:
        return " ".join(v.split()) if isinstance(v, str) else v

    @field_validator("phone")
    @classmethod
    def _phone(cls, v: str | None) -> str | None:
        return clean_phone(v) if v else v


@router.patch("/{user_id}", response_model=AdminUserDetail)
async def update_user(
    user_id: uuid.UUID, body: UserPatch, p: SuperPrincipal, db: DB, background: BackgroundTasks
) -> AdminUserDetail:
    _web_only(p)
    user = await _locked(db, user_id)
    changes = body.model_dump(exclude_unset=True)
    if changes.get("is_active") is False and (user.id == p.user.id or user.is_superuser):
        raise Conflict("Platform admins cannot be deactivated here", code="cannot_deactivate_admin")
    if changes.get("nationality"):
        code = changes["nationality"].upper()
        if code not in ISO_COUNTRIES:
            raise AppError("Unknown country code", code="invalid_country")
        user.nationality = code
    if changes.get("email") and changes["email"].lower() != user.email:
        email = changes["email"].lower()
        if await db.scalar(select(User.id).where(func.lower(User.email) == email, User.id != user.id)):
            raise Conflict("Another account already uses this email", code="email_taken")
        user.email = email
        user.email_verified_at = None  # the new inbox has not been confirmed yet
    for key in ("full_name", "phone", "locale", "is_active"):
        if changes.get(key) is not None:
            value = changes[key]
            setattr(user, key, value.strip() if isinstance(value, str) else value)
    if "admin_notes" in changes:
        user.admin_notes = (changes["admin_notes"] or "").strip() or None
    new_signal = False
    if "email" in changes or "phone" in changes:  # the new email/phone joins the duplicate checks
        new_signal = await review.record(db, user, with_identity=True)
    if changes.get("email_verified") is True:
        await accounts.mark_verified(db, user)  # starts the trial if the account is approved
    elif changes.get("email_verified") is False:
        user.email_verified_at = None
    logged = {k: v for k, v in body.model_dump(mode="json", exclude_unset=True).items() if k != "admin_notes"}
    await audit(db, p, "admin.user_updated", "user", user.id, logged)
    try:
        await db.commit()
    except IntegrityError as exc:  # another account took the address between the check and the commit
        await db.rollback()
        raise Conflict("Another account already uses this email", code="email_taken") from exc
    if new_signal:
        background.add_task(review.refresh_counts_soon, user.id, new_signal)
    return await _detail(db, user_id)


@router.post("/{user_id}/password-reset", response_model=Message, status_code=202)
async def send_password_reset(user_id: uuid.UUID, p: SuperPrincipal, db: DB, background: BackgroundTasks) -> Message:
    """Email the user a link to choose a new password (the admin never sees or sets passwords)."""
    _web_only(p)
    user = await _locked(db, user_id)
    background.add_task(accounts.send_password_reset, user.id)
    await audit(db, p, "admin.user_password_reset", "user", user.id, {"email": user.email})
    await db.commit()
    return Message(message="Reset link sent")


class GrantPackageIn(BaseModel):
    workspace_id: uuid.UUID
    package_id: uuid.UUID
    method: PaymentMethod = PaymentMethod.CASH
    # Defaults to the package price; 0 records a gift.
    amount: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    reference: str | None = Field(default=None, max_length=200)
    note: str | None = Field(default=None, max_length=500)
    # Sent again on a retry or double click: the package is granted once (stored in the unique provider_order_id).
    request_id: uuid.UUID


@router.post("/{user_id}/grant-package", response_model=AdminUserDetail)
async def grant_package(user_id: uuid.UUID, body: GrantPackageIn, p: SuperPrincipal, db: DB) -> AdminUserDetail:
    """Record a package the customer paid for outside the site (or a gift): its credits land as a purchase, so the
    workspace leaves the trial, and the payment shows in their history and in the revenue figures."""
    _web_only(p)
    if body.method == PaymentMethod.PAYPAL:
        raise AppError("PayPal payments are recorded by PayPal checkout", code="invalid_method")
    member = await db.scalar(
        select(WorkspaceMember).where(
            WorkspaceMember.user_id == user_id, WorkspaceMember.workspace_id == body.workspace_id
        )
    )
    package = await db.get(CreditPackage, body.package_id)
    if member is None or package is None:
        raise NotFound("Workspace or package not found")
    order_id = f"admin:{body.request_id}"
    if await db.scalar(select(TopUpRequest.id).where(TopUpRequest.provider_order_id == order_id)):
        return await _detail(db, user_id)  # already granted by an earlier copy of this request
    amount = package.price if body.amount is None else body.amount
    method = PaymentMethod.COMPLIMENTARY if amount == 0 else body.method
    tx = await credit_svc.grant(
        db,
        body.workspace_id,
        package.credits,
        CreditKind.PURCHASE,
        note=(body.note or "").strip() or f"{package.name_en} · {method}",
        created_by=p.user.id,
    )
    topup = TopUpRequest(
        workspace_id=body.workspace_id,
        package_id=package.id,
        credits=package.credits,
        amount=amount,
        currency=package.currency,
        method=method,
        reference=body.reference,
        status=TopUpStatus.APPROVED,
        created_by=p.user.id,
        reviewed_by=p.user.id,
        reviewed_at=datetime.now(UTC),
        transaction_id=tx.id,
        provider_order_id=order_id,
    )
    db.add(topup)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()  # also undoes this request's credit grant
        if "provider_order_id" not in str(exc.orig):
            raise
        return await _detail(db, user_id)  # the same request id raced in from another click: that one granted it
    await notify_events.payment_received(db, topup, manual=True)
    await audit(
        db,
        p,
        "admin.package_granted",
        "workspace",
        body.workspace_id,
        {"package": str(package.id), "credits": package.credits, "amount": str(amount), "method": method},
    )
    await db.commit()
    return await _detail(db, user_id)
