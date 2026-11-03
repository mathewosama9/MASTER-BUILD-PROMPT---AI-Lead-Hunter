"""Sends the queued email and Telegram deliveries (run by the notify worker every few seconds).

Email is paced by `PlatformSettings.email_rate_per_minute` (shared hosting SMTP accounts have send caps), so a
broadcast to thousands drains over time instead of getting the mailbox blocked. Failed sends retry with backoff.
"""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import Notification, NotificationDelivery, TelegramAccount, User
from app.models.enums import DeliveryStatus, NotifyChannel, TelegramLinkStatus
from app.services import credits as credit_svc
from app.services import mailer
from app.services import notifications as telegram_api
from app.services import providers as provider_svc
from app.services.notify import templates
from app.services.notify.catalog import KINDS
from app.services.notify.dispatcher import unsubscribe_urls

log = logging.getLogger(__name__)
MAX_ATTEMPTS = 5
TELEGRAM_BATCH = 40


class Skip(Exception):
    """The channel can't be used for this user any more: stop trying."""


async def platform_bot_token(db: AsyncSession) -> str | None:
    token = get_settings().telegram_bot_token
    if token:
        return token
    creds, _ = await provider_svc.credentials_for(db, None, "telegram")
    return creds.get("bot_token")


async def _due(db: AsyncSession, channel: str, limit: int) -> list[tuple[NotificationDelivery, Notification, User]]:
    if limit <= 0:
        return []
    rows = await db.execute(
        select(NotificationDelivery, Notification, User)
        .join(Notification, Notification.id == NotificationDelivery.notification_id)
        .join(User, User.id == Notification.user_id)
        .where(
            NotificationDelivery.channel == channel,
            NotificationDelivery.status == DeliveryStatus.PENDING,
            NotificationDelivery.next_attempt_at <= datetime.now(UTC),
        )
        .order_by(NotificationDelivery.next_attempt_at)
        .limit(limit)
        .with_for_update(of=NotificationDelivery, skip_locked=True)
    )
    return [tuple(r) for r in rows.all()]  # type: ignore[misc]


async def _email_room(db: AsyncSession) -> int:
    rate = max(1, (await credit_svc.platform_settings(db)).email_rate_per_minute)
    sent = await db.scalar(
        select(func.count()).where(
            NotificationDelivery.channel == NotifyChannel.EMAIL,
            NotificationDelivery.status == DeliveryStatus.SENT,
            NotificationDelivery.sent_at >= datetime.now(UTC) - timedelta(minutes=1),
        )
    )
    return rate - int(sent or 0)


async def _send_email(note: Notification, user: User) -> None:
    spec = KINDS.get(note.kind)
    page_url = headers = None
    if spec is not None and spec.marketing:
        page_url, one_click = unsubscribe_urls(user.id, note.kind)
        headers = {"List-Unsubscribe": f"<{one_click}>", "List-Unsubscribe-Post": "List-Unsubscribe=One-Click"}
    subject, text, body = templates.render_email(note.kind, user.locale, note.title, note.body, note.link, page_url)
    if not mailer.configured():
        await mailer.send_email(user.email, subject, text, body)  # logs it outside production
        raise Skip("SMTP is not configured")
    if not await mailer.send_email(user.email, subject, text, body, headers=headers):
        raise RuntimeError("SMTP send failed")


async def _send_telegram(db: AsyncSession, token: str | None, note: Notification, user: User) -> None:
    if not token:
        raise Skip("no Telegram bot token")
    chats = (
        await db.scalars(
            select(TelegramAccount.chat_id).where(
                TelegramAccount.user_id == user.id, TelegramAccount.status == TelegramLinkStatus.APPROVED
            )
        )
    ).all()
    if not chats:
        raise Skip("no linked Telegram account")
    text = templates.render_telegram(note.title, note.body, note.link)
    buttons = templates.telegram_buttons(note.kind, user.locale, note.params or {})
    ok = 0
    for chat_id in chats:
        payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
        if buttons:
            payload["reply_markup"] = buttons
        if await telegram_api._send(token, "sendMessage", payload) is not None:
            ok += 1
    if not ok:
        raise RuntimeError("Telegram send failed")


def _record(row: NotificationDelivery, error: Exception | None) -> None:
    now = datetime.now(UTC)
    row.attempts += 1
    if error is None:
        row.status = DeliveryStatus.SENT
        row.sent_at = now
        row.last_error = None
    elif isinstance(error, Skip):
        row.status = DeliveryStatus.SKIPPED
        row.last_error = str(error)[:500]
    else:
        row.last_error = f"{type(error).__name__}: {error}"[:500]
        if row.attempts >= MAX_ATTEMPTS:
            row.status = DeliveryStatus.FAILED
        else:
            row.next_attempt_at = now + timedelta(minutes=2**row.attempts)


async def deliver_due(db: AsyncSession) -> dict[str, int]:
    """Send what is due now; returns counts by outcome.

    Each send is committed on its own, so a crash never re-sends what already went out, and one bad message (an odd
    header, a provider hiccup) is retried on its own instead of failing the rest of the batch. One run at a time:
    the worker task holds a lock (workers/tasks.py), which also keeps the email pace honest.
    """
    counts = {"sent": 0, "skipped": 0, "retry": 0, "failed": 0}
    batches = [
        (NotifyChannel.EMAIL, await _due(db, NotifyChannel.EMAIL, await _email_room(db))),
        (NotifyChannel.TELEGRAM, await _due(db, NotifyChannel.TELEGRAM, TELEGRAM_BATCH)),
    ]
    token = await platform_bot_token(db) if batches[1][1] else None
    outcome = {DeliveryStatus.SENT: "sent", DeliveryStatus.SKIPPED: "skipped", DeliveryStatus.FAILED: "failed"}
    for channel, rows in batches:
        for row, note, user in rows:
            error: Exception | None = None
            try:
                if not user.is_active or user.deleted_at is not None:
                    raise Skip("user inactive")
                if channel == NotifyChannel.EMAIL:
                    await _send_email(note, user)
                else:
                    await _send_telegram(db, token, note, user)
            except Exception as exc:  # noqa: BLE001 - recorded on the row and retried; never blocks the queue
                if not isinstance(exc, Skip | RuntimeError):
                    log.exception("notification delivery crashed", extra={"delivery": str(row.id)})
                error = exc
            _record(row, error)
            await db.commit()  # also releases this row's lock
            counts[outcome.get(row.status, "retry")] += 1
    await db.commit()
    if any(counts.values()):
        log.info("notification deliveries", extra=counts)
    return counts
