"""Platform admin (superusers only): pricing settings, credit packages, top-up review, workspaces, contact requests.

Every change is recorded in the audit log.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Query, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, or_, select
from sqlalchemy.orm import undefer

from app.api.deps import DB, SuperPrincipal, audit
from app.core.errors import AppError, Conflict, NotFound
from app.models import (
    Campaign,
    ContactRequest,
    CreditPackage,
    CreditTransaction,
    Testimonial,
    TopUpRequest,
    User,
    Workspace,
    WorkspaceMember,
)
from app.models.enums import CreditKind, PaymentMethod, Role, TestimonialSource, TestimonialStatus, TopUpStatus
from app.research.providers.registry import discovery_providers
from app.schemas.billing import PackageOut, TopUpOut
from app.schemas.campaign import ResearchDefaults
from app.schemas.common import Message, Page
from app.schemas.marketing import TestimonialOut
from app.services import credits as credit_svc
from app.services import paypal, receipts
from app.services import providers as provider_svc

router = APIRouter(prefix="/admin", tags=["admin"])


# ---------------------------------------------------------------- platform settings


class SettingsIO(BaseModel):
    trial_days: int = Field(ge=0, le=365)
    trial_credits: int = Field(ge=0, le=100_000)
    credits_per_contact: int = Field(ge=1, le=100)
    payment_instructions_ar: str = Field(default="", max_length=4000)
    payment_instructions_en: str = Field(default="", max_length=4000)
    research_defaults: ResearchDefaults = Field(default_factory=ResearchDefaults)

    @field_validator("research_defaults", mode="before")
    @classmethod
    def _defaults(cls, v: object) -> object:
        return v or {}  # an empty row means "use the built-in defaults"

    @field_validator("research_defaults")
    @classmethod
    def _known_sources(cls, v: ResearchDefaults) -> ResearchDefaults:
        known = {p.info.key for p in discovery_providers()} - {"demo", "manual", "facebook", "import"}
        unknown = [k for k in v.sources if k not in known]
        if unknown:
            raise ValueError(f"Unknown or user-list sources: {', '.join(unknown)}")
        v.sources = list(dict.fromkeys(v.sources))
        return v


@router.get("/settings", response_model=SettingsIO)
async def get_settings_(p: SuperPrincipal, db: DB) -> SettingsIO:
    s = await credit_svc.platform_settings(db)
    await db.commit()
    return SettingsIO.model_validate(s, from_attributes=True)


@router.put("/settings", response_model=SettingsIO)
async def put_settings(body: SettingsIO, p: SuperPrincipal, db: DB) -> SettingsIO:
    s = await credit_svc.platform_settings(db)
    before = SettingsIO.model_validate(s, from_attributes=True).model_dump()
    after = body.model_dump()
    for k, v in after.items():
        setattr(s, k, v)
    changed = {k: v for k, v in after.items() if before[k] != v}
    await audit(db, p, "admin.settings_updated", "platform_settings", 1, changed)
    await db.commit()
    return body


# ---------------------------------------------------------------- PayPal account (services/paypal.py)


class PayPalStatus(BaseModel):
    connected: bool
    mode: str | None = None
    client_id: str | None = None  # masked
    webhook: bool = False
    webhook_url: str


class PayPalConnectIn(BaseModel):
    client_id: str = Field(min_length=10, max_length=200)
    client_secret: str = Field(min_length=10, max_length=200)
    mode: Literal["live", "sandbox"] = "live"


def _paypal_status(creds: dict[str, str]) -> PayPalStatus:
    cid = creds.get("client_id")
    return PayPalStatus(
        connected=bool(creds),
        mode=creds.get("mode") if creds else None,
        client_id=f"{cid[:6]}…{cid[-4:]}" if cid else None,
        webhook=bool(creds.get("webhook_id")),
        webhook_url=paypal.webhook_url(),
    )


@router.get("/paypal", response_model=PayPalStatus)
async def paypal_status(p: SuperPrincipal, db: DB) -> PayPalStatus:
    return _paypal_status(await paypal.credentials(db))


@router.put("/paypal", response_model=PayPalStatus)
async def paypal_connect(body: PayPalConnectIn, p: SuperPrincipal, db: DB) -> PayPalStatus:
    """Check the REST app's credentials with PayPal, register the webhook, and store them encrypted."""
    creds = await paypal.connect(body.client_id, body.client_secret, body.mode)
    await provider_svc.save_credentials(db, None, paypal.KEY, {"webhook_id": "", **creds})
    await audit(db, p, "admin.paypal_connected", "paypal", None, {"mode": body.mode})
    await db.commit()
    return _paypal_status(creds)


@router.delete("/paypal", response_model=PayPalStatus)
async def paypal_disconnect(p: SuperPrincipal, db: DB) -> PayPalStatus:
    await provider_svc.save_credentials(
        db, None, paypal.KEY, {"client_id": "", "client_secret": "", "mode": "", "webhook_id": ""}
    )
    await audit(db, p, "admin.paypal_disconnected", "paypal", None)
    await db.commit()
    return _paypal_status({})


# ---------------------------------------------------------------- packages


class PackageIn(BaseModel):
    name_ar: str = Field(min_length=1, max_length=120)
    name_en: str = Field(min_length=1, max_length=120)
    credits: int = Field(ge=1, le=1_000_000)
    price: Decimal = Field(ge=0, max_digits=12, decimal_places=2)
    currency: str = Field(default="USD", pattern="^[A-Z]{3}$")
    active: bool = True
    sort: int = 0
    featured: bool = False  # shown as "most popular" on the pricing page


class PackagePatch(BaseModel):
    name_ar: str | None = Field(default=None, min_length=1, max_length=120)
    name_en: str | None = Field(default=None, min_length=1, max_length=120)
    credits: int | None = Field(default=None, ge=1, le=1_000_000)
    price: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    currency: str | None = Field(default=None, pattern="^[A-Z]{3}$")
    active: bool | None = None
    sort: int | None = None
    featured: bool | None = None


class AdminPackageOut(PackageOut):
    active: bool
    sort: int


@router.get("/packages", response_model=list[AdminPackageOut])
async def list_packages(p: SuperPrincipal, db: DB) -> list[AdminPackageOut]:
    rows = await db.scalars(
        select(CreditPackage).order_by(CreditPackage.active.desc(), CreditPackage.sort, CreditPackage.credits)
    )
    return [AdminPackageOut.model_validate(r) for r in rows]


@router.post("/packages", response_model=AdminPackageOut, status_code=201)
async def create_package(body: PackageIn, p: SuperPrincipal, db: DB) -> AdminPackageOut:
    pkg = CreditPackage(**body.model_dump())
    db.add(pkg)
    await db.flush()
    await audit(db, p, "admin.package_created", "credit_package", pkg.id, body.model_dump(mode="json"))
    await db.commit()
    await db.refresh(pkg)  # numeric(12,2) as stored, e.g. 175 -> 175.00
    return AdminPackageOut.model_validate(pkg)


@router.patch("/packages/{package_id}", response_model=AdminPackageOut)
async def update_package(package_id: uuid.UUID, body: PackagePatch, p: SuperPrincipal, db: DB) -> AdminPackageOut:
    """Edit or (de)activate. Packages are never deleted: past top-ups keep pointing at them."""
    pkg = await db.get(CreditPackage, package_id)
    if pkg is None:
        raise NotFound("Package not found")
    changes = body.model_dump(exclude_unset=True)
    for k, v in changes.items():
        setattr(pkg, k, v)
    await audit(
        db, p, "admin.package_updated", "credit_package", pkg.id, body.model_dump(mode="json", exclude_unset=True)
    )
    await db.commit()
    await db.refresh(pkg)  # numeric(12,2) as stored, e.g. 175 -> 175.00
    return AdminPackageOut.model_validate(pkg)


# ---------------------------------------------------------------- top-up review


class AdminTopUpOut(TopUpOut):
    workspace_id: uuid.UUID
    workspace_name: str
    requested_by: str | None


async def _topup_rows(db: DB, where: list) -> list[AdminTopUpOut]:
    rows = (
        await db.execute(
            select(TopUpRequest, Workspace.name, User.email)
            .join(Workspace, Workspace.id == TopUpRequest.workspace_id)
            .outerjoin(User, User.id == TopUpRequest.created_by)
            .where(*where)
            .order_by(TopUpRequest.created_at.desc())
            .limit(200)
        )
    ).all()
    return [
        AdminTopUpOut(
            **TopUpOut.model_validate(t).model_dump(), workspace_id=t.workspace_id, workspace_name=n, requested_by=e
        )
        for t, n, e in rows
    ]


@router.get("/topups", response_model=list[AdminTopUpOut])
async def list_topups(p: SuperPrincipal, db: DB, status: TopUpStatus | None = None) -> list[AdminTopUpOut]:
    return await _topup_rows(db, [TopUpRequest.status == status] if status else [])


@router.get("/topups/{topup_id}/receipt")
async def topup_receipt(topup_id: uuid.UUID, p: SuperPrincipal, db: DB) -> Response:
    topup = await db.scalar(
        select(TopUpRequest).options(undefer(TopUpRequest.receipt_data)).where(TopUpRequest.id == topup_id)
    )
    if topup is None or topup.receipt_data is None:
        raise NotFound("Receipt not found")
    return receipts.response(topup)


async def _pending_for_review(db: DB, topup_id: uuid.UUID) -> TopUpRequest:
    # Row lock: two admins clicking at once cannot both approve (and grant twice).
    topup = await db.scalar(select(TopUpRequest).where(TopUpRequest.id == topup_id).with_for_update())
    if topup is None:
        raise NotFound("Top-up request not found")
    if topup.status != TopUpStatus.PENDING:
        raise Conflict(f"This request was already {topup.status}", code="already_reviewed")
    if topup.method == PaymentMethod.PAYPAL:  # settled by PayPal itself, never by hand
        raise Conflict("PayPal payments are confirmed automatically", code="paypal_auto")
    return topup


@router.post("/topups/{topup_id}/approve", response_model=AdminTopUpOut)
async def approve_topup(topup_id: uuid.UUID, p: SuperPrincipal, db: DB) -> AdminTopUpOut:
    topup = await _pending_for_review(db, topup_id)
    tx = await credit_svc.grant(
        db,
        topup.workspace_id,
        topup.credits,
        CreditKind.PURCHASE,
        note=f"Top-up {topup.amount} {topup.currency} via {topup.method}",
        created_by=p.user.id,
    )
    topup.status = TopUpStatus.APPROVED
    topup.reviewed_by = p.user.id
    topup.reviewed_at = datetime.now(UTC)
    topup.transaction_id = tx.id
    await audit(
        db,
        p,
        "admin.topup_approved",
        "topup",
        topup.id,
        {"credits": topup.credits, "workspace": str(topup.workspace_id)},
    )
    await db.commit()
    return (await _topup_rows(db, [TopUpRequest.id == topup.id]))[0]


class RejectIn(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


@router.post("/topups/{topup_id}/reject", response_model=AdminTopUpOut)
async def reject_topup(topup_id: uuid.UUID, body: RejectIn, p: SuperPrincipal, db: DB) -> AdminTopUpOut:
    topup = await _pending_for_review(db, topup_id)
    topup.status = TopUpStatus.REJECTED
    topup.reason = body.reason.strip()
    topup.reviewed_by = p.user.id
    topup.reviewed_at = datetime.now(UTC)
    await audit(db, p, "admin.topup_rejected", "topup", topup.id, {"reason": topup.reason})
    await db.commit()
    return (await _topup_rows(db, [TopUpRequest.id == topup.id]))[0]


# ---------------------------------------------------------------- workspaces


class AdminWorkspaceOut(BaseModel):
    id: uuid.UUID
    name: str
    owner_email: str | None
    created_at: datetime
    balance: int
    credits_used: int
    campaigns: int
    trial_ends_at: datetime | None
    on_trial: bool
    billing_exempt: bool
    suspended_at: datetime | None
    # Feeds the public site's live preview (see public.py).
    is_showcase: bool = False


@router.get("/workspaces", response_model=Page[AdminWorkspaceOut])
async def list_workspaces(
    p: SuperPrincipal,
    db: DB,
    q: str | None = Query(None, max_length=200),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
) -> Page[AdminWorkspaceOut]:
    owner = (
        select(User.email)
        .join(WorkspaceMember, WorkspaceMember.user_id == User.id)
        .where(WorkspaceMember.workspace_id == Workspace.id, WorkspaceMember.role == Role.OWNER)
        .order_by(WorkspaceMember.created_at)
        .limit(1)
        .scalar_subquery()
    )
    used = (
        select(func.coalesce(-func.sum(CreditTransaction.delta), 0))
        .where(CreditTransaction.workspace_id == Workspace.id, CreditTransaction.kind == CreditKind.CAMPAIGN_CHARGE)
        .scalar_subquery()
    )
    campaigns = (
        select(func.count(Campaign.id))
        .where(Campaign.workspace_id == Workspace.id, Campaign.deleted_at.is_(None))
        .scalar_subquery()
    )
    purchased = (
        select(func.count(CreditTransaction.id))
        .where(CreditTransaction.workspace_id == Workspace.id, CreditTransaction.kind == CreditKind.PURCHASE)
        .scalar_subquery()
    )
    where = [Workspace.deleted_at.is_(None)]
    if q:
        like = f"%{q.strip()}%"
        member_match = (
            select(WorkspaceMember.workspace_id)
            .join(User, User.id == WorkspaceMember.user_id)
            .where(User.email.ilike(like))
        )
        where.append(or_(Workspace.name.ilike(like), Workspace.id.in_(member_match)))
    total = await db.scalar(select(func.count()).select_from(Workspace).where(*where))
    rows = (
        await db.execute(
            select(Workspace, owner, used, campaigns, purchased)
            .where(*where)
            .order_by(Workspace.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    showcase = (await credit_svc.platform_settings(db)).showcase_workspace_id
    items = [
        AdminWorkspaceOut(
            id=w.id,
            name=w.name,
            owner_email=o,
            created_at=w.created_at,
            balance=w.credit_balance,
            credits_used=int(u or 0),
            campaigns=int(c or 0),
            trial_ends_at=w.trial_ends_at,
            on_trial=w.trial_ends_at is not None and not pu,
            billing_exempt=w.billing_exempt,
            suspended_at=w.suspended_at,
            is_showcase=w.id == showcase,
        )
        for w, o, u, c, pu in rows
    ]
    return Page(items=items, total=int(total or 0), page=page, page_size=page_size)


class AdjustIn(BaseModel):
    delta: int = Field(ge=-1_000_000, le=1_000_000)
    note: str = Field(min_length=3, max_length=500)


@router.post("/workspaces/{workspace_id}/adjust", response_model=Message)
async def adjust_credits(workspace_id: uuid.UUID, body: AdjustIn, p: SuperPrincipal, db: DB) -> Message:
    if body.delta == 0:
        raise AppError("The adjustment must not be zero")
    if await db.get(Workspace, workspace_id) is None:
        raise NotFound("Workspace not found")
    try:
        tx = await credit_svc.adjust(db, workspace_id, body.delta, note=body.note.strip(), created_by=p.user.id)
    except credit_svc.InsufficientCredits as exc:
        raise Conflict("The balance cannot go below zero", code="insufficient_credits") from exc
    await audit(db, p, "admin.credits_adjusted", "workspace", workspace_id, {"delta": body.delta, "note": body.note})
    await db.commit()
    return Message(message=f"Balance is now {tx.balance_after}")


class WorkspacePatch(BaseModel):
    suspended: bool | None = None
    billing_exempt: bool | None = None
    trial_ends_at: datetime | None = None
    showcase: bool | None = None


@router.patch("/workspaces/{workspace_id}", response_model=Message)
async def update_workspace(workspace_id: uuid.UUID, body: WorkspacePatch, p: SuperPrincipal, db: DB) -> Message:
    ws = await db.get(Workspace, workspace_id)
    if ws is None:
        raise NotFound("Workspace not found")
    changes = body.model_dump(exclude_unset=True)
    if "suspended" in changes:
        if changes["suspended"] and workspace_id == p.workspace_id:
            raise Conflict("You cannot suspend your own workspace")
        ws.suspended_at = datetime.now(UTC) if changes["suspended"] else None
    if "billing_exempt" in changes and changes["billing_exempt"] is not None:
        ws.billing_exempt = changes["billing_exempt"]
    if "trial_ends_at" in changes:
        ws.trial_ends_at = changes["trial_ends_at"]
    if changes.get("showcase") is not None:
        s = await credit_svc.platform_settings(db)
        if changes["showcase"]:
            s.showcase_workspace_id = workspace_id
        elif s.showcase_workspace_id == workspace_id:
            s.showcase_workspace_id = None
    await audit(
        db, p, "admin.workspace_updated", "workspace", workspace_id, body.model_dump(mode="json", exclude_unset=True)
    )
    await db.commit()
    return Message(message="Workspace updated")


# ---------------------------------------------------------------- contact requests


class ContactOut(BaseModel):
    id: uuid.UUID
    name: str
    company: str | None
    email: str
    phone: str | None
    interest: str
    message: str
    locale: str
    status: str
    created_at: datetime
    handled_at: datetime | None


@router.get("/contacts", response_model=list[ContactOut])
async def list_contacts(
    p: SuperPrincipal, db: DB, status: str | None = Query(None, pattern="^(new|handled)$")
) -> list[ContactOut]:
    q = select(ContactRequest).order_by(ContactRequest.created_at.desc()).limit(200)
    if status:
        q = q.where(ContactRequest.status == status)
    return [ContactOut.model_validate(r, from_attributes=True) for r in await db.scalars(q)]


@router.post("/contacts/{contact_id}/handled", response_model=ContactOut)
async def mark_contact_handled(contact_id: uuid.UUID, p: SuperPrincipal, db: DB) -> ContactOut:
    c = await db.get(ContactRequest, contact_id)
    if c is None:
        raise NotFound("Contact request not found")
    c.status = "handled"
    c.handled_by = p.user.id
    c.handled_at = datetime.now(UTC)
    await audit(db, p, "admin.contact_handled", "contact_request", c.id)
    await db.commit()
    return ContactOut.model_validate(c, from_attributes=True)


# ---------------------------------------------------------------- testimonials


class TestimonialIn(BaseModel):
    __test__ = False  # not a pytest test class

    author_name: str = Field(min_length=2, max_length=120)
    author_role: str | None = Field(default=None, max_length=120)
    company: str | None = Field(default=None, max_length=200)
    city: str | None = Field(default=None, max_length=120)
    country: str | None = Field(default=None, min_length=2, max_length=2)
    rating: int = Field(default=5, ge=1, le=5)
    body_ar: str = Field(default="", max_length=1000)
    body_en: str = Field(default="", max_length=1000)
    status: TestimonialStatus = TestimonialStatus.APPROVED
    is_featured: bool = False
    sort: int = Field(default=0, ge=0, le=1000)


class TestimonialPatch(BaseModel):
    __test__ = False

    author_name: str | None = Field(default=None, min_length=2, max_length=120)
    author_role: str | None = Field(default=None, max_length=120)
    company: str | None = Field(default=None, max_length=200)
    city: str | None = Field(default=None, max_length=120)
    country: str | None = Field(default=None, min_length=2, max_length=2)
    rating: int | None = Field(default=None, ge=1, le=5)
    body_ar: str | None = Field(default=None, max_length=1000)
    body_en: str | None = Field(default=None, max_length=1000)
    status: TestimonialStatus | None = None
    is_featured: bool | None = None
    sort: int | None = Field(default=None, ge=0, le=1000)


@router.get("/testimonials", response_model=list[TestimonialOut])
async def list_testimonials(
    p: SuperPrincipal, db: DB, status: TestimonialStatus | None = Query(None)
) -> list[TestimonialOut]:
    q = select(Testimonial).order_by(Testimonial.status, Testimonial.sort, Testimonial.created_at.desc()).limit(500)
    if status:
        q = q.where(Testimonial.status == status)
    return [TestimonialOut.model_validate(t) for t in await db.scalars(q)]


@router.post("/testimonials", response_model=TestimonialOut, status_code=201)
async def create_testimonial(body: TestimonialIn, p: SuperPrincipal, db: DB) -> TestimonialOut:
    if not (body.body_ar.strip() or body.body_en.strip()):
        raise AppError("Write the review in Arabic or English", code="empty_review", status_code=422)
    t = Testimonial(**body.model_dump(), source=TestimonialSource.MANUAL, consent_publish=True)
    if body.status != TestimonialStatus.PENDING:
        t.reviewed_at = datetime.now(UTC)
    db.add(t)
    await db.flush()
    await audit(db, p, "admin.testimonial_created", "testimonial", t.id)
    await db.commit()
    return TestimonialOut.model_validate(t)


@router.patch("/testimonials/{testimonial_id}", response_model=TestimonialOut)
async def update_testimonial(
    testimonial_id: uuid.UUID, body: TestimonialPatch, p: SuperPrincipal, db: DB
) -> TestimonialOut:
    t = await db.get(Testimonial, testimonial_id)
    if t is None:
        raise NotFound("Testimonial not found")
    changes = body.model_dump(exclude_unset=True)
    # A user's own review is published only if they agreed to it.
    if (
        changes.get("status") == TestimonialStatus.APPROVED
        and t.source == TestimonialSource.IN_APP
        and not t.consent_publish
    ):
        raise Conflict("The author did not agree to publish this review", code="no_consent")
    for k, v in changes.items():
        setattr(t, k, v)
    if "status" in changes:
        t.reviewed_at = datetime.now(UTC)
    await audit(db, p, "admin.testimonial_updated", "testimonial", t.id, {k: str(v) for k, v in changes.items()})
    await db.commit()
    return TestimonialOut.model_validate(t)


@router.delete("/testimonials/{testimonial_id}", response_model=Message)
async def delete_testimonial(testimonial_id: uuid.UUID, p: SuperPrincipal, db: DB) -> Message:
    t = await db.get(Testimonial, testimonial_id)
    if t is None:
        raise NotFound("Testimonial not found")
    await db.delete(t)
    await audit(db, p, "admin.testimonial_deleted", "testimonial", testimonial_id)
    await db.commit()
    return Message(message="deleted")
