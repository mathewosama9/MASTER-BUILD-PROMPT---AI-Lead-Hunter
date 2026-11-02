"""The client's own credits: balance, trial, ledger, packages and purchases (PayPal; legacy manual top-ups)."""

import logging
import math
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Query, Request, Response
from sqlalchemy import func, select
from sqlalchemy.orm import undefer

from app.api.deps import DB, CurrentPrincipal, audit, require_role
from app.core.db import get_sessionmaker
from app.core.errors import AppError, Conflict, NotFound
from app.models import CreditPackage, CreditTransaction, TopUpRequest, Workspace
from app.models.enums import PaymentMethod, Role, TopUpStatus
from app.schemas.billing import (
    BillingSummary,
    PackageOut,
    PayPalOrderIn,
    PayPalOrderOut,
    PayPalOrderRef,
    TopUpIn,
    TopUpOut,
    TransactionOut,
)
from app.schemas.common import Page
from app.services import credits as credit_svc
from app.services import paypal, receipts
from app.services.notifications import notify_platform_admins

log = logging.getLogger(__name__)
router = APIRouter(prefix="/billing", tags=["billing"])
webhook_router = APIRouter(prefix="/payments", tags=["billing"])

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
        select(func.count()).where(
            TopUpRequest.workspace_id == ws.id,
            TopUpRequest.status == TopUpStatus.PENDING,
            TopUpRequest.method != PaymentMethod.PAYPAL,  # an unfinished checkout is not awaiting review
        )
    )
    paypal_enabled = bool(await paypal.credentials(db))
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
        paypal_enabled=paypal_enabled,
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
    """Legacy: the client paid outside the app (InstaPay / bank / Vodafone Cash) and uploads the receipt for
    review. The dashboard sells through PayPal checkout now; this stays for existing API clients."""
    if body.method == PaymentMethod.PAYPAL:
        raise Conflict("Pay with PayPal through checkout", code="use_checkout")
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


# ---------------------------------------------------------------- PayPal checkout (services/paypal.py)


@router.post("/paypal/orders", response_model=PayPalOrderOut, status_code=201, dependencies=[require_role(Role.ADMIN)])
async def paypal_order(body: PayPalOrderIn, p: CurrentPrincipal, db: DB) -> PayPalOrderOut:
    creds = await paypal.require_credentials(db)
    package = await db.get(CreditPackage, body.package_id)
    if package is None or not package.active:
        raise NotFound("This package is not available")
    topup = TopUpRequest(
        workspace_id=p.workspace_id,
        package_id=package.id,
        credits=package.credits,
        amount=package.price,
        currency=package.currency,
        method=PaymentMethod.PAYPAL,
        status=TopUpStatus.PENDING,
        created_by=p.user.id,
    )
    db.add(topup)
    await db.flush()
    order_id, approve_url = await paypal.create_order(
        creds,
        amount=package.price,
        currency=package.currency,
        reference=str(topup.id),
        description=f"Rasd - {package.name_en} ({package.credits} credits)",
        locale=p.user.locale or "ar",
    )
    topup.provider_order_id = order_id
    topup.reference = order_id
    await audit(db, p, "billing.paypal_order", "topup", topup.id, {"package": str(package.id), "order": order_id})
    await db.commit()
    return PayPalOrderOut(order_id=order_id, approve_url=approve_url)


async def _own_order(db: DB, p: CurrentPrincipal, order_id: str) -> TopUpRequest:
    topup = await db.scalar(
        select(TopUpRequest).where(
            TopUpRequest.provider_order_id == order_id, TopUpRequest.workspace_id == p.workspace_id
        )
    )
    if topup is None:
        raise NotFound("Payment not found")
    return topup


@router.post("/paypal/capture", response_model=TopUpOut, dependencies=[require_role(Role.ADMIN)])
async def paypal_capture(body: PayPalOrderRef, p: CurrentPrincipal, db: DB, background: BackgroundTasks) -> TopUpOut:
    """The client is back from PayPal: capture the payment and add the credits."""
    topup = await _own_order(db, p, body.order_id)
    if topup.status == TopUpStatus.PENDING:
        order = await paypal.capture_order(await paypal.require_credentials(db), body.order_id)
        topup, granted = await paypal.settle(db, body.order_id, order)
        await audit(db, p, "billing.paypal_captured", "topup", topup.id, {"order": body.order_id})
        await db.commit()
        if granted:
            background.add_task(_notify_paid, topup.id)
    return TopUpOut.model_validate(topup)


@router.post("/paypal/cancel", response_model=TopUpOut, dependencies=[require_role(Role.ADMIN)])
async def paypal_cancel(body: PayPalOrderRef, p: CurrentPrincipal, db: DB) -> TopUpOut:
    """The client backed out at PayPal: close the unfinished checkout."""
    topup = await _own_order(db, p, body.order_id)
    await db.refresh(topup, with_for_update=True)
    if topup.status == TopUpStatus.PENDING:
        topup.status = TopUpStatus.REJECTED
        topup.reason = "Cancelled at PayPal"
        await db.commit()
    return TopUpOut.model_validate(topup)


@webhook_router.post("/paypal/webhook", include_in_schema=False)
async def paypal_webhook(request: Request, db: DB, background: BackgroundTasks) -> dict:
    """Backup for a client who paid but never came back to the dashboard. Verified with PayPal; no session."""
    creds = await paypal.credentials(db)
    event = await request.json()
    headers = {k.lower(): v for k, v in request.headers.items()}
    if not creds or not await paypal.verify_webhook(creds, headers, event):
        raise AppError("Invalid webhook", code="invalid_webhook", status_code=400)
    resource = event.get("resource") or {}
    kind = event.get("event_type")
    order_id = None
    if kind == "CHECKOUT.ORDER.APPROVED":
        order_id = resource.get("id")
    elif kind == "PAYMENT.CAPTURE.COMPLETED":
        order_id = ((resource.get("supplementary_data") or {}).get("related_ids") or {}).get("order_id")
    if not order_id:
        return {"ok": True}
    status = await db.scalar(select(TopUpRequest.status).where(TopUpRequest.provider_order_id == order_id))
    if status != TopUpStatus.PENDING:
        return {"ok": True}  # not ours, or already settled / cancelled
    order = await paypal.capture_order(creds, order_id)
    topup, granted = await paypal.settle(db, order_id, order)
    await db.commit()
    if granted:
        background.add_task(_notify_paid, topup.id)
    return {"ok": True}


async def _notify_paid(topup_id: uuid.UUID) -> None:
    async with get_sessionmaker()() as db:
        topup = await db.get(TopUpRequest, topup_id)
        if topup is None:
            return
        ws = await db.get(Workspace, topup.workspace_id)
        try:
            await notify_platform_admins(
                db,
                f"✅ PayPal payment received\nWorkspace: {ws.name if ws else topup.workspace_id}\n"
                f"Amount: {topup.amount} {topup.currency} · {topup.credits} credits added\n"
                f"Order: {topup.provider_order_id}",
            )
        except Exception:  # noqa: BLE001 - the payment is recorded either way
            log.warning("payment notification failed", exc_info=True)


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
