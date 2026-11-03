"""Platform admin: notification policy (which kinds go out, on which channels, whether users may turn them off),
the email pace, test sends, and broadcasts to an audience. Every change is recorded in the audit log."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Query
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import func, or_, select

from app.api.deps import DB, SuperPrincipal, audit
from app.core.errors import AppError
from app.models import Broadcast, NotificationDelivery, User
from app.models.enums import DeliveryStatus
from app.schemas.common import Message, Page
from app.services import credits as credit_svc
from app.services import mailer
from app.services.notify import audience as audience_svc
from app.services.notify import broadcast as broadcast_svc
from app.services.notify.catalog import KINDS, clean_policy, full_policy
from app.services.notify.delivery import platform_bot_token
from app.services.notify.templates import email_layout

router = APIRouter(prefix="/admin", tags=["admin"])


# ---------------------------------------------------------------- policy


class KindPolicy(BaseModel):
    key: str
    category: str
    mandatory: bool
    admin: bool
    enabled: bool
    channels: dict[str, bool]
    user_can_disable: bool


class PolicyOut(BaseModel):
    kinds: list[KindPolicy]
    email_rate_per_minute: int
    smtp_configured: bool
    telegram_configured: bool
    pending: int
    failed_24h: int


class PolicyIn(BaseModel):
    policy: dict[str, dict]
    email_rate_per_minute: int = Field(ge=1, le=1000)


async def _policy_out(db: DB) -> PolicyOut:
    s = await credit_svc.platform_settings(db)
    policy = full_policy(s.notification_policy)
    pending = await db.scalar(select(func.count()).where(NotificationDelivery.status == DeliveryStatus.PENDING))
    failed = await db.scalar(
        select(func.count()).where(
            NotificationDelivery.status == DeliveryStatus.FAILED,
            NotificationDelivery.updated_at >= datetime.now(UTC) - timedelta(days=1),
        )
    )
    return PolicyOut(
        kinds=[
            KindPolicy(key=k.key, category=k.category, mandatory=k.mandatory, admin=k.admin, **policy[k.key])
            for k in KINDS.values()
        ],
        email_rate_per_minute=s.email_rate_per_minute,
        smtp_configured=mailer.configured(),
        telegram_configured=bool(await platform_bot_token(db)),
        pending=int(pending or 0),
        failed_24h=int(failed or 0),
    )


@router.get("/notifications/policy", response_model=PolicyOut)
async def get_policy(p: SuperPrincipal, db: DB) -> PolicyOut:
    out = await _policy_out(db)
    await db.commit()
    return out


@router.put("/notifications/policy", response_model=PolicyOut)
async def put_policy(body: PolicyIn, p: SuperPrincipal, db: DB) -> PolicyOut:
    s = await credit_svc.platform_settings(db)
    s.notification_policy = clean_policy(body.policy)
    s.email_rate_per_minute = body.email_rate_per_minute
    await audit(
        db,
        p,
        "admin.notification_policy_updated",
        "platform_settings",
        1,
        {"policy": s.notification_policy, "email_rate_per_minute": body.email_rate_per_minute},
    )
    await db.commit()
    return await _policy_out(db)


@router.post("/notifications/test-email", response_model=Message)
async def test_email(p: SuperPrincipal) -> Message:
    """Send a test email to the admin now (not through the outbox) to check the SMTP settings."""
    if not mailer.configured():
        raise AppError("SMTP is not configured on the server (SMTP_HOST / SMTP_FROM)", code="smtp_not_configured")
    lang = "ar" if p.user.locale == "ar" else "en"
    text = "رسالة تجريبية من رصد: الإيميل شغال." if lang == "ar" else "Test email from Rasd: email delivery works."
    if not await mailer.send_email(p.user.email, "Rasd test email", text, email_layout(lang, text)):
        raise AppError("The SMTP server did not accept the email; check the server log", code="smtp_failed")
    return Message(message=f"Sent to {p.user.email}")


# ---------------------------------------------------------------- broadcasts


class AudienceIn(BaseModel):
    type: Literal["all", "admins", "trial", "paying", "low_balance", "inactive_30d", "suspended", "users", "workspaces"]
    ids: list[uuid.UUID] = Field(default_factory=list, max_length=500)

    @model_validator(mode="after")
    def _ids_for_lists(self) -> "AudienceIn":
        if self.type in ("users", "workspaces") and not self.ids:
            raise ValueError("Pick at least one recipient")
        return self


class BroadcastIn(BaseModel):
    kind: Literal["announcement", "marketing"] = "announcement"
    title_ar: str = Field(default="", max_length=300)
    title_en: str = Field(default="", max_length=300)
    body_ar: str = Field(default="", max_length=4000)
    body_en: str = Field(default="", max_length=4000)
    link: str | None = Field(default=None, max_length=500)
    audience: AudienceIn
    channels: list[Literal["in_app", "email", "telegram"]] = Field(min_length=1)

    @field_validator("title_ar", "title_en", "body_ar", "body_en", "link")
    @classmethod
    def _strip(cls, v: str | None) -> str | None:
        return v.strip() if isinstance(v, str) else v

    @field_validator("link")
    @classmethod
    def _safe_link(cls, v: str | None) -> str | None:
        # "//host" is a link to another site, not a dashboard path.
        if v and not ((v.startswith("/") and not v.startswith("//")) or v.startswith("https://")):
            raise ValueError("The link must be a dashboard path (/app/...) or start with https://")
        return v or None

    @model_validator(mode="after")
    def _some_text(self) -> "BroadcastIn":
        if not (self.title_ar or self.title_en):
            raise ValueError("Write a title in Arabic or English")
        return self

    def to_row(self, created_by: uuid.UUID) -> Broadcast:
        return Broadcast(
            created_by=created_by,
            kind=self.kind,
            title_ar=self.title_ar,
            title_en=self.title_en,
            body_ar=self.body_ar,
            body_en=self.body_en,
            link=self.link,
            audience=self.audience.model_dump(mode="json"),
            channels=list(dict.fromkeys(self.channels)),
        )


class BroadcastOut(BaseModel):
    id: uuid.UUID
    kind: str
    title_ar: str
    title_en: str
    body_ar: str
    body_en: str
    link: str | None
    audience: dict
    channels: list[str]
    status: str
    recipients: int
    created_at: datetime
    created_by_email: str | None
    stats: dict


@router.post("/broadcasts/preview")
async def preview_broadcast(body: AudienceIn, p: SuperPrincipal, db: DB) -> dict:
    return {"recipients": await audience_svc.count(db, body.model_dump(mode="json"))}


@router.post("/broadcasts/test", response_model=Message)
async def test_broadcast(body: BroadcastIn, p: SuperPrincipal, db: DB) -> Message:
    """Queue the message to the admin alone on the chosen channels; nothing is saved as a broadcast."""
    reached = await broadcast_svc.send_test(db, body.to_row(p.user.id), p.user)
    await db.commit()
    if not reached:
        raise AppError("Nothing to send: these channels are off for you or not set up", code="nothing_sent")
    return Message(message="Test queued")


@router.post("/broadcasts", response_model=BroadcastOut, status_code=201)
async def create_broadcast(body: BroadcastIn, p: SuperPrincipal, db: DB, background: BackgroundTasks) -> BroadcastOut:
    b = body.to_row(p.user.id)
    b.status = "sending"
    db.add(b)
    await db.flush()
    await audit(db, p, "admin.broadcast_sent", "broadcast", b.id, {"audience": b.audience, "channels": b.channels})
    await db.commit()
    background.add_task(broadcast_svc.launch, b.id)
    return (await _broadcast_rows(db, [Broadcast.id == b.id]))[0]


async def _broadcast_rows(db: DB, where: list, offset: int = 0, limit: int = 1) -> list[BroadcastOut]:
    rows = (
        await db.execute(
            select(Broadcast, User.email)
            .outerjoin(User, User.id == Broadcast.created_by)
            .where(*where)
            .order_by(Broadcast.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
    ).all()
    stats = await broadcast_svc.stats(db, [b.id for b, _ in rows])
    return [
        BroadcastOut(
            id=b.id,
            kind=b.kind,
            title_ar=b.title_ar,
            title_en=b.title_en,
            body_ar=b.body_ar,
            body_en=b.body_en,
            link=b.link,
            audience=b.audience,
            channels=b.channels,
            status=b.status,
            recipients=b.recipients,
            created_at=b.created_at,
            created_by_email=email,
            stats=stats[b.id],
        )
        for b, email in rows
    ]


@router.get("/broadcasts", response_model=Page[BroadcastOut])
async def list_broadcasts(
    p: SuperPrincipal, db: DB, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100)
) -> Page[BroadcastOut]:
    total = await db.scalar(select(func.count()).select_from(Broadcast))
    items = await _broadcast_rows(db, [], (page - 1) * page_size, page_size)
    return Page(items=items, total=int(total or 0), page=page, page_size=page_size)


class RecipientOut(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str


@router.get("/notifications/recipients", response_model=list[RecipientOut])
async def search_recipients(
    p: SuperPrincipal, db: DB, q: str = Query(min_length=2, max_length=200)
) -> list[RecipientOut]:
    """Users to pick for a broadcast to specific people."""
    like = f"%{q.strip().lower()}%"
    rows = await db.scalars(
        select(User)
        .where(
            User.deleted_at.is_(None),
            or_(func.lower(User.email).like(like), func.lower(User.full_name).like(like)),
        )
        .order_by(User.email)
        .limit(20)
    )
    return [RecipientOut(id=u.id, email=u.email, full_name=u.full_name) for u in rows.all()]
