"""Daily notification checks: trial reminders, the admin's daily summary, and inbox cleanup."""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Campaign, CreditTransaction, Notification, TopUpRequest, User, Workspace
from app.models.enums import CampaignStatus, CreditKind, TopUpStatus
from app.services.notify.dispatcher import notify, notify_admins

log = logging.getLogger(__name__)
TRIAL_REMINDER_DAYS = 3
KEEP_READ_DAYS = 90


def _on_trial():
    return ~exists().where(
        CreditTransaction.workspace_id == Workspace.id, CreditTransaction.kind == CreditKind.PURCHASE
    )


def _not_told(kind: str):
    """No `kind` notification for this workspace yet (a workspace has one trial, so one reminder)."""
    return ~exists().where(Notification.workspace_id == Workspace.id, Notification.kind == kind)


async def trial_reminders(db: AsyncSession) -> int:
    now = datetime.now(UTC)
    base = (
        Workspace.deleted_at.is_(None),
        Workspace.billing_exempt.is_(False),
        Workspace.suspended_at.is_(None),
        Workspace.trial_ends_at.is_not(None),
        _on_trial(),
    )
    sent = 0
    ending = await db.scalars(
        select(Workspace).where(
            *base,
            Workspace.trial_ends_at > now,
            Workspace.trial_ends_at <= now + timedelta(days=TRIAL_REMINDER_DAYS),
            _not_told("trial_ending"),
        )
    )
    for ws in ending.all():
        days = max(1, (ws.trial_ends_at - now).days + 1)
        sent += await notify(
            db,
            "trial_ending",
            workspace_id=ws.id,
            params={"days": days, "date": ws.trial_ends_at.date().isoformat()},
            link="/app/billing",
        )
    ended = await db.scalars(
        select(Workspace).where(
            *base,
            Workspace.trial_ends_at <= now,
            Workspace.trial_ends_at > now - timedelta(days=7),
            _not_told("trial_ended"),
        )
    )
    for ws in ended.all():
        sent += await notify(db, "trial_ended", workspace_id=ws.id, link="/app/billing")
    await db.commit()
    return sent


async def admin_digest(db: AsyncSession) -> int:
    since = datetime.now(UTC) - timedelta(days=1)
    new_users = await db.scalar(select(func.count()).where(User.created_at >= since))
    payments, revenue = (
        await db.execute(
            select(func.count(), func.coalesce(func.sum(TopUpRequest.amount), 0)).where(
                TopUpRequest.status == TopUpStatus.APPROVED,
                TopUpRequest.reviewed_at >= since,
                TopUpRequest.currency == "USD",
            )
        )
    ).one()
    campaigns = await db.scalar(select(func.count()).where(Campaign.created_at >= since, Campaign.is_demo.is_(False)))
    failed = await db.scalar(
        select(func.count()).where(
            Campaign.completed_at >= since, Campaign.status == CampaignStatus.FAILED, Campaign.is_demo.is_(False)
        )
    )
    n = await notify_admins(
        db,
        "admin_daily_digest",
        {
            "new_users": new_users or 0,
            "payments": payments or 0,
            "revenue": f"{revenue:.2f}",
            "campaigns": campaigns or 0,
            "failed": failed or 0,
        },
        link="/app/admin",
    )
    await db.commit()
    return n


async def cleanup(db: AsyncSession) -> int:
    cutoff = datetime.now(UTC) - timedelta(days=KEEP_READ_DAYS)
    res = await db.execute(
        delete(Notification).where(
            ((Notification.read_at.is_not(None)) | (Notification.in_app.is_(False))),
            Notification.created_at < cutoff,
        )
    )
    await db.commit()
    return res.rowcount or 0


async def daily(db: AsyncSession) -> dict[str, int]:
    return {
        "trial": await trial_reminders(db),
        "digest": await admin_digest(db),
        "cleaned": await cleanup(db),
    }
