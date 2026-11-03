"""The signed-in user's notifications (the bell) and notification settings; one-click email unsubscribe."""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import func, select, update

from app.api.deps import DB, CurrentPrincipal
from app.core.errors import AppError, NotFound
from app.models import Notification, User
from app.schemas.common import Message
from app.services import credits as credit_svc
from app.services.notify.catalog import CHANNELS, KINDS, clean_prefs, policy_for, user_choice
from app.services.notify.dispatcher import decode_unsubscribe, telegram_linked

router = APIRouter(prefix="/notifications", tags=["notifications"])


class NotificationOut(BaseModel):
    id: uuid.UUID
    kind: str
    title: str
    body: str
    link: str | None
    read_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class NotificationPage(BaseModel):
    items: list[NotificationOut]
    total: int
    unread: int


def _mine(user_id: uuid.UUID) -> tuple:
    return (Notification.user_id == user_id, Notification.in_app.is_(True))


async def _unread(db: DB, user_id: uuid.UUID) -> int:
    return int(await db.scalar(select(func.count()).where(*_mine(user_id), Notification.read_at.is_(None))) or 0)


@router.get("", response_model=NotificationPage)
async def list_notifications(
    p: CurrentPrincipal,
    db: DB,
    unread: bool = False,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
) -> NotificationPage:
    where = list(_mine(p.user.id))
    if unread:
        where.append(Notification.read_at.is_(None))
    total = await db.scalar(select(func.count()).where(*where))
    rows = await db.scalars(
        select(Notification)
        .where(*where)
        .order_by(Notification.created_at.desc())
        .offset((page - 1) * limit)
        .limit(limit)
    )
    return NotificationPage(
        items=[NotificationOut.model_validate(n) for n in rows.all()],
        total=int(total or 0),
        unread=await _unread(db, p.user.id),
    )


@router.get("/unread-count")
async def unread_count(p: CurrentPrincipal, db: DB) -> dict:
    return {"unread": await _unread(db, p.user.id)}


@router.post("/{notification_id}/read", response_model=Message)
async def mark_read(notification_id: uuid.UUID, p: CurrentPrincipal, db: DB) -> Message:
    n = await db.scalar(select(Notification).where(Notification.id == notification_id, *_mine(p.user.id)))
    if n is None:
        raise NotFound("Notification not found")
    if n.read_at is None:
        n.read_at = datetime.now(UTC)
        await db.commit()
    return Message(message="ok")


@router.post("/read-all", response_model=Message)
async def mark_all_read(p: CurrentPrincipal, db: DB) -> Message:
    await db.execute(
        update(Notification).where(*_mine(p.user.id), Notification.read_at.is_(None)).values(read_at=datetime.now(UTC))
    )
    await db.commit()
    return Message(message="ok")


# ---------------------------------------------------------------- preferences


class ChannelState(BaseModel):
    allowed: bool  # the admin's policy sends this kind on this channel
    on: bool  # what the user gets (allowed and not turned off)


class KindPrefs(BaseModel):
    key: str
    category: str
    locked: bool  # mandatory, or the admin doesn't let users turn it off
    channels: dict[str, ChannelState]


class PrefsOut(BaseModel):
    kinds: list[KindPrefs]
    telegram_linked: bool
    email_verified: bool


class PrefsIn(BaseModel):
    prefs: dict[str, dict[str, bool]]


async def _prefs_out(db: DB, user: User) -> PrefsOut:
    policy = (await credit_svc.platform_settings(db)).notification_policy
    kinds = []
    for kind in KINDS.values():
        if kind.admin and not user.is_superuser:
            continue
        pol = policy_for(policy, kind)
        if not pol["enabled"]:
            continue
        locked = kind.mandatory or not pol["user_can_disable"]
        channels = {}
        for c in CHANNELS:
            allowed = pol["channels"][c.value]
            on = allowed and (locked or user_choice(user.notification_prefs, kind, c.value))
            channels[c.value] = ChannelState(allowed=allowed, on=on)
        if any(ch.allowed for ch in channels.values()):
            kinds.append(KindPrefs(key=kind.key, category=kind.category, locked=locked, channels=channels))
    return PrefsOut(
        kinds=kinds,
        telegram_linked=bool(await telegram_linked(db, [user.id])),
        email_verified=user.email_verified_at is not None,
    )


@router.get("/preferences", response_model=PrefsOut)
async def get_preferences(p: CurrentPrincipal, db: DB) -> PrefsOut:
    return await _prefs_out(db, p.user)


@router.put("/preferences", response_model=PrefsOut)
async def put_preferences(body: PrefsIn, p: CurrentPrincipal, db: DB) -> PrefsOut:
    merged = dict(p.user.notification_prefs or {})
    for key, choices in clean_prefs(body.prefs, admin=p.user.is_superuser).items():
        merged[key] = {**(merged.get(key) or {}), **choices}
    p.user.notification_prefs = merged
    await db.commit()
    return await _prefs_out(db, p.user)


@router.post("/unsubscribe")
async def unsubscribe(db: DB, token: str = Query(max_length=2000)) -> dict:
    """From the link in a news email, or the mail app's one-click unsubscribe. No sign-in: the token is the proof."""
    claims = decode_unsubscribe(token)
    kind = KINDS.get((claims or {}).get("kind", ""))
    user = await db.get(User, uuid.UUID(claims["sub"])) if claims and kind else None
    if user is None or kind is None:
        raise AppError("This unsubscribe link is invalid", code="invalid_token")
    prefs = dict(user.notification_prefs or {})
    prefs[kind.key] = {**(prefs.get(kind.key) or {}), "email": False}
    user.notification_prefs = prefs
    await db.commit()
    return {"kind": kind.key}
