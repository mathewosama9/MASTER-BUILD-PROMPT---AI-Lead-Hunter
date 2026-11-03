"""`notify()`: the one entry point for telling users (or platform admins) that something happened.

It writes the bell notification and queues the email/Telegram deliveries in the caller's transaction, so nothing is
sent for an event that rolls back. The caller commits; the notify worker sends the queued rows (delivery.py).
"""

import logging
import uuid
from collections.abc import Iterable, Sequence
from urllib.parse import quote

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import create_purpose_token, decode_purpose_token
from app.models import Notification, NotificationDelivery, TelegramAccount, User, WorkspaceMember
from app.models.enums import ROLE_RANK, NotifyChannel, Role, TelegramLinkStatus
from app.services import credits as credit_svc
from app.services.notify import templates
from app.services.notify.catalog import KINDS, channels_for

log = logging.getLogger(__name__)
UNSUBSCRIBE = "unsubscribe"
UNSUBSCRIBE_DAYS = 365


async def _workspace_users(db: AsyncSession, workspace_id: uuid.UUID, min_role: Role) -> list[User]:
    roles = [r for r, rank in ROLE_RANK.items() if rank >= ROLE_RANK[min_role]]
    return list(
        (
            await db.scalars(
                select(User)
                .join(WorkspaceMember, WorkspaceMember.user_id == User.id)
                .where(WorkspaceMember.workspace_id == workspace_id, WorkspaceMember.role.in_(roles))
            )
        ).all()
    )


async def platform_admins(db: AsyncSession) -> list[User]:
    return list((await db.scalars(select(User).where(User.is_superuser.is_(True)))).all())


async def telegram_linked(db: AsyncSession, user_ids: Iterable[uuid.UUID]) -> set[uuid.UUID]:
    ids = list(user_ids)
    if not ids:
        return set()
    rows = await db.scalars(
        select(TelegramAccount.user_id).where(
            TelegramAccount.user_id.in_(ids), TelegramAccount.status == TelegramLinkStatus.APPROVED
        )
    )
    return set(rows.all())


def reachable(user: User, channel: str, *, mandatory: bool, has_telegram: bool) -> bool:
    if channel == NotifyChannel.TELEGRAM:
        return has_telegram
    if channel == NotifyChannel.EMAIL:
        # Unconfirmed inboxes get only security emails: anything else could land with someone who mistyped.
        return mandatory or user.email_verified_at is not None
    return True


async def notify(
    db: AsyncSession,
    kind: str,
    *,
    users: Sequence[User] | None = None,
    workspace_id: uuid.UUID | None = None,
    min_role: Role = Role.ADMIN,
    params: dict | None = None,
    link: str | None = None,
    skip_channels: Iterable[str] = (),
    only_channels: Iterable[str] | None = None,
    broadcast_id: uuid.UUID | None = None,
) -> int:
    """Queue `kind` for its recipients; returns how many users it reached on at least one channel. Never raises.

    Recipients: platform admins for admin kinds, else `users`, else the members of `workspace_id` with at least
    `min_role` (billing news goes to the people who pay, not to every analyst).
    """
    spec = KINDS.get(kind)
    if spec is None:
        log.error("unknown notification kind %s", kind)
        return 0
    try:
        async with db.begin_nested():
            return await _queue(
                db,
                spec.key,
                users,
                workspace_id,
                min_role,
                params or {},
                link,
                set(skip_channels),
                set(only_channels) if only_channels is not None else None,
                broadcast_id,
            )
    except Exception:  # noqa: BLE001 - a notification must never undo the event it reports
        log.exception("queueing notification failed", extra={"kind": kind})
        return 0


async def _queue(
    db: AsyncSession,
    kind: str,
    users: Sequence[User] | None,
    workspace_id: uuid.UUID | None,
    min_role: Role,
    params: dict,
    link: str | None,
    skip: set[str],
    only: set[str] | None,
    broadcast_id: uuid.UUID | None,
) -> int:
    spec = KINDS[kind]
    if spec.admin:
        recipients = await platform_admins(db)
    elif users is not None:
        recipients = list(users)
    elif workspace_id is not None:
        recipients = await _workspace_users(db, workspace_id, min_role)
    else:
        return 0
    recipients = [u for u in recipients if u.is_active and u.deleted_at is None]
    if not recipients:
        return 0
    policy = (await credit_svc.platform_settings(db)).notification_policy
    with_telegram = await telegram_linked(db, [u.id for u in recipients])
    reached = 0
    for user in recipients:
        channels = channels_for(policy, user.notification_prefs, spec) - skip
        if only is not None:
            channels &= only
        channels = {
            c for c in channels if reachable(user, c, mandatory=spec.mandatory, has_telegram=user.id in with_telegram)
        }
        if not channels:
            continue
        title, body = templates.render(kind, user.locale, params)
        note = Notification(
            id=uuid.uuid4(),  # set here, so the deliveries can point at it without a flush per recipient
            user_id=user.id,
            workspace_id=workspace_id,
            kind=kind,
            title=title[:300],
            body=body,
            link=link,
            params=params,
            broadcast_id=broadcast_id,
            in_app=NotifyChannel.IN_APP in channels,
        )
        db.add(note)
        for channel in sorted(channels - {NotifyChannel.IN_APP}):
            db.add(NotificationDelivery(notification_id=note.id, channel=channel))
        reached += 1
    await db.flush()
    return reached


async def notify_admins(db: AsyncSession, kind: str, params: dict | None = None, link: str | None = None) -> int:
    return await notify(db, kind, params=params, link=link)


def unsubscribe_token(user_id: uuid.UUID, kind: str) -> str:
    return create_purpose_token(UNSUBSCRIBE, user_id, UNSUBSCRIBE_DAYS * 24 * 60, kind=kind)


def decode_unsubscribe(token: str) -> dict | None:
    return decode_purpose_token(UNSUBSCRIBE, token)


def unsubscribe_urls(user_id: uuid.UUID, kind: str) -> tuple[str, str]:
    """(page the email links to, one-click POST URL for the List-Unsubscribe header)."""
    base = get_settings().frontend_url.rstrip("/")
    token = quote(unsubscribe_token(user_id, kind))
    return f"{base}/unsubscribe?token={token}", f"{base}/api/v1/notifications/unsubscribe?token={token}"
