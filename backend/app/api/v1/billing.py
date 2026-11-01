"""The client's own credits: balance, trial, ledger, packages and manual top-up requests."""

import logging
import math
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Query, Response
from sqlalchemy import func, select
from sqlalchemy.orm import undefer

from app.api.deps import DB, CurrentPrincipal, audit, require_role
from app.core.db import get_sessionmaker
from app.core.errors import Conflict, NotFound
from app.models import CreditPackage, CreditTransaction, TopUpRequest, Workspace
from app.models.enums import Role, TopUpStatus
from app.schemas.billing import BillingSummary, PackageOut, TopUpIn, TopUpOut, TransactionOut
from app.schemas.common import Page
from app.services import credits as credit_svc
from app.services import receipts
from app.services.notifications import notify_platform_admins

log = logging.getLogger(__name__)
router = APIRouter(prefix="/billing", tags=["billing"])

MAX_PENDING_TOPUPS = 3


@router.get("/summary", response_model=BillingSummary)
async def summary(p: CurrentPrincipal, db: DB) -> BillingSummary:
    ws = await db.get(Workspace, p.workspace_id)
    await db.refresh(ws, attribute_names=["credit_balance", "trial_ends_at", "billing_exempt"])
    settings = await credit_svc.platform_settings(db)
    on_trial = await credit_svc.on_trial(db, ws)
    now = datetime.now(UTC)
    days_left = None
    if on_trial and ws.trial_ends_at:
        days_left = max(0, math.ceil((ws.trial_ends_at - now).total_seconds() / 86400))
    pending = await db.scalar(
        select(func.count()).where(TopUpRequest.workspace_id == ws.id, TopUpRequest.status == TopUpStatus.PENDING)
    )
    awaiting = await credit_svc.awaiting_verification(db, ws)
    await db.commit()  # persists the default settings row the first time
    return BillingSummary(
        billing_exempt=ws.billing_exempt,
        balance=ws.credit_balance,
        on_trial=on_trial,
        trial_ends_at=ws.trial_ends_at if on_trial else None,
        trial_days_left=days_left,
        trial_expired=bool(on_trial and ws.trial_ends_at and ws.trial_ends_at <= now),
        awaiting_verification=awaiting,
        credits_per_contact=settings.credits_per_contact,
        low_balance=not ws.billing_exempt and ws.credit_balance < credit_svc.LOW_BALANCE_CREDITS,
        pending_topups=int(pending or 0),
        payment_instructions_ar=settings.payment_instructions_ar,
        payment_instructions_en=settings.payment_instructions_en,
    )


@router.get("/transactions", response_model=Page[TransactionOut])
async def transactions(
    p: CurrentPrincipal,
    db: DB,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
) -> Page[TransactionOut]:
    where = CreditTransaction.workspace_id == p.workspace_id
    total = await db.scalar(select(func.count()).where(where))
    rows = await db.scalars(
        select(CreditTransaction)
        .where(where)
        .order_by(CreditTransaction.created_at.desc(), CreditTransaction.balance_after)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = [TransactionOut.model_validate(r) for r in rows]
    return Page(items=items, total=int(total or 0), page=page, page_size=page_size)


async def active_packages(db: DB) -> list[CreditPackage]:
    rows = await db.scalars(
        select(CreditPackage).where(CreditPackage.active.is_(True)).order_by(CreditPackage.sort, CreditPackage.credits)
    )
    return list(rows)


@router.get("/packages", response_model=list[PackageOut])
async def packages(p: CurrentPrincipal, db: DB) -> list[PackageOut]:
    return [PackageOut.model_validate(x) for x in await active_packages(db)]


@router.post("/topups", response_model=TopUpOut, status_code=201, dependencies=[require_role(Role.ADMIN)])
async def request_topup(body: TopUpIn, p: CurrentPrincipal, db: DB, background: BackgroundTasks) -> TopUpOut:
    """The client paid outside the app (InstaPay / bank / Vodafone Cash) and uploads the receipt for review."""
    package = await db.get(CreditPackage, body.package_id)
    if package is None or not package.active:
        raise NotFound("This package is not available")
    pending = await db.scalar(
        select(func.count()).where(
            TopUpRequest.workspace_id == p.workspace_id, TopUpRequest.status == TopUpStatus.PENDING
        )
    )
    if (pending or 0) >= MAX_PENDING_TOPUPS:
        raise Conflict("You already have requests awaiting review; wait for them first", code="too_many_pending")
    data, kind = receipts.decode(body.receipt_base64)
    topup = TopUpRequest(
        workspace_id=p.workspace_id,
        package_id=package.id,
        credits=package.credits,
        amount=package.price,
        currency=package.currency,
        method=body.method,
        reference=(body.reference or "").strip() or None,
        receipt_filename=body.receipt_filename,
        receipt_content_type=kind,
        receipt_data=data,
        status=TopUpStatus.PENDING,
        created_by=p.user.id,
    )
    db.add(topup)
    await db.flush()
    await audit(db, p, "billing.topup_requested", "topup", topup.id, {"package": str(package.id)})
    await db.commit()
    ws = await db.get(Workspace, p.workspace_id)
    background.add_task(
        _notify_topup,
        f"💳 New top-up request\nWorkspace: {ws.name if ws else p.workspace_id}\nBy: {p.user.email}\n"
        f"Package: {package.name_en} ({package.credits} credits)\nAmount: {package.price} {package.currency}\n"
        f"Method: {body.method}\nReference: {topup.reference or '—'}\nReview it in the admin dashboard.",
    )
    return TopUpOut.model_validate(topup)


async def _notify_topup(text: str) -> None:
    async with get_sessionmaker()() as db:
        try:
            await notify_platform_admins(db, text)
        except Exception:  # noqa: BLE001 - the request is saved either way
            log.warning("top-up notification failed", exc_info=True)


@router.get("/topups", response_model=list[TopUpOut])
async def my_topups(p: CurrentPrincipal, db: DB) -> list[TopUpOut]:
    rows = await db.scalars(
        select(TopUpRequest)
        .where(TopUpRequest.workspace_id == p.workspace_id)
        .order_by(TopUpRequest.created_at.desc())
        .limit(50)
    )
    return [TopUpOut.model_validate(r) for r in rows]


@router.get("/topups/{topup_id}/receipt")
async def my_receipt(topup_id: uuid.UUID, p: CurrentPrincipal, db: DB) -> Response:
    topup = await db.scalar(
        select(TopUpRequest)
        .options(undefer(TopUpRequest.receipt_data))
        .where(TopUpRequest.id == topup_id, TopUpRequest.workspace_id == p.workspace_id)
    )
    if topup is None or topup.receipt_data is None:
        raise NotFound("Receipt not found")
    return receipts.response(topup)
