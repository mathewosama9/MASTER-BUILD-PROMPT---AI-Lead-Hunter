"""Notifications for events that several call sites share (campaign outcome, payments). Callers commit."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Campaign, TopUpRequest, User, Workspace
from app.models.enums import CampaignStatus, NotifyChannel
from app.services.notify.dispatcher import notify, notify_admins


async def campaign_finished(db: AsyncSession, campaign: Campaign) -> None:
    """Tell the person who started the search how it went, and admins when a real one failed."""
    creator = await db.get(User, campaign.created_by) if campaign.created_by else None
    target = {"users": [creator]} if creator else {"workspace_id": campaign.workspace_id}
    link = f"/app/campaigns/{campaign.id}"
    # Searches started from the bot already get their result card in that chat.
    skip = {NotifyChannel.TELEGRAM} if campaign.telegram_chat_id else set()
    stats = campaign.stats or {}
    if campaign.status == CampaignStatus.FAILED:
        await notify(db, "campaign_failed", **target, params={"name": campaign.name}, link=link, skip_channels=skip)
        if not campaign.is_demo:
            ws = await db.get(Workspace, campaign.workspace_id)
            await notify_admins(
                db,
                "admin_campaign_failed",
                {"name": campaign.name, "workspace": ws.name if ws else "", "error": (campaign.last_error or "")[:300]},
                link="/app/admin?tab=usage",
            )
        return
    await notify(
        db,
        "campaign_completed",
        **target,
        params={"name": campaign.name, "found": stats.get("unique_leads", 0), "qualified": stats.get("qualified", 0)},
        link=link,
        skip_channels=skip,
    )
    if "credits_exhausted" in (campaign.last_error or ""):
        await notify(
            db,
            "credits_exhausted",
            workspace_id=campaign.workspace_id,
            params={"name": campaign.name},
            link="/app/billing",
        )


async def payment_received(db: AsyncSession, topup: TopUpRequest, *, manual: bool) -> None:
    """Credits from a purchase landed: the buyer's workspace hears about it, and the platform admins do for PayPal
    payments (a manual top-up was approved by an admin)."""
    ws = await db.get(Workspace, topup.workspace_id)
    params = {
        "credits": topup.credits,
        "amount": f"{topup.amount:.2f}",
        "currency": topup.currency,
        "balance": ws.credit_balance if ws else "",
    }
    await notify(
        db,
        "topup_approved" if manual else "payment_succeeded",
        workspace_id=topup.workspace_id,
        params=params,
        link="/app/billing",
    )
    if manual:  # the admin approved it by hand, so they already know
        return
    buyer = await db.get(User, topup.created_by) if topup.created_by else None
    await notify_admins(
        db,
        "admin_new_payment",
        {
            **params,
            "workspace": ws.name if ws else "",
            "email": buyer.email if buyer else "",
            "method": topup.method,
        },
        link="/app/admin?tab=payments",
    )
