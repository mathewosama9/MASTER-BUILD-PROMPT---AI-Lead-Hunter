"""Admin broadcasts: one message to an audience on the channels the admin picked.

Users' own choices still apply (anyone can turn off news and offers, unless the admin's policy forbids it), and
marketing emails always carry an unsubscribe link.
"""

import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_sessionmaker
from app.models import Broadcast, Notification, NotificationDelivery, User
from app.services.notify import audience
from app.services.notify.dispatcher import notify

log = logging.getLogger(__name__)
BATCH = 500
STALE_MINUTES = 5


def params_of(b: Broadcast) -> dict:
    return {"title_ar": b.title_ar, "title_en": b.title_en, "body_ar": b.body_ar, "body_en": b.body_en}


async def send_test(db: AsyncSession, b: Broadcast, admin: User) -> int:
    """The broadcast to the admin alone, without saving it. Caller commits."""
    return await notify(db, b.kind, users=[admin], params=params_of(b), link=b.link, only_channels=b.channels)


async def launch(broadcast_id: uuid.UUID) -> None:
    """Queue the broadcast for its whole audience, a batch per transaction (FastAPI background task).

    Safe to run again: people who already have this broadcast are skipped, so `resume_stale` can finish one that a
    restart interrupted."""
    async with get_sessionmaker()() as db:
        await _launch(db, broadcast_id)


async def _launch(db: AsyncSession, broadcast_id: uuid.UUID) -> None:
    b = await db.get(Broadcast, broadcast_id)
    if b is None or b.status != "sending":
        return
    done = select(Notification.user_id).where(Notification.broadcast_id == b.id)
    ids = list((await db.scalars(audience.user_ids_query(b.audience).where(User.id.not_in(done)))).all())
    for start in range(0, len(ids), BATCH):
        users = list((await db.scalars(select(User).where(User.id.in_(ids[start : start + BATCH])))).all())
        await notify(
            db, b.kind, users=users, params=params_of(b), link=b.link, only_channels=b.channels, broadcast_id=b.id
        )
        b.updated_at = datetime.now(UTC)  # progress mark for resume_stale
        await db.commit()
    b.recipients = int(await db.scalar(select(func.count()).where(Notification.broadcast_id == b.id)) or 0)
    b.status = "sent"
    await db.commit()
    log.info("broadcast queued", extra={"broadcast": str(b.id), "recipients": b.recipients})


async def resume_stale(db: AsyncSession) -> int:
    """Finish broadcasts still "sending" with no progress for STALE_MINUTES (the API restarted mid-way)."""
    cutoff = datetime.now(UTC) - timedelta(minutes=STALE_MINUTES)
    ids = list(
        (
            await db.scalars(select(Broadcast.id).where(Broadcast.status == "sending", Broadcast.updated_at < cutoff))
        ).all()
    )
    for bid in ids:
        log.warning("resuming interrupted broadcast", extra={"broadcast": str(bid)})
        await _launch(db, bid)
    return len(ids)


async def stats(db: AsyncSession, ids: list[uuid.UUID]) -> dict[uuid.UUID, dict]:
    """{broadcast id: {"in_app": n, "read": n, "email": {status: n}, "telegram": {status: n}}}."""
    out: dict[uuid.UUID, dict] = {i: {"in_app": 0, "read": 0, "email": {}, "telegram": {}} for i in ids}
    if not ids:
        return out
    rows = await db.execute(
        select(Notification.broadcast_id, func.count(), func.count(Notification.read_at))
        .where(Notification.broadcast_id.in_(ids), Notification.in_app.is_(True))
        .group_by(Notification.broadcast_id)
    )
    for bid, total, read in rows.all():
        out[bid]["in_app"], out[bid]["read"] = total, read
    rows = await db.execute(
        select(Notification.broadcast_id, NotificationDelivery.channel, NotificationDelivery.status, func.count())
        .join(Notification, Notification.id == NotificationDelivery.notification_id)
        .where(Notification.broadcast_id.in_(ids))
        .group_by(Notification.broadcast_id, NotificationDelivery.channel, NotificationDelivery.status)
    )
    for bid, channel, status, n in rows.all():
        out[bid].setdefault(channel, {})[status] = n
    return out
