"""Outbound notifications for campaign lifecycle.

Telegram messages are sent with the Bot API directly from the worker so notifications work even when the
bot process restarts. Numbers always come from the stored campaign stats.
"""

import logging
import time
from html import escape

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import Business, Campaign, CampaignLead, TelegramAccount, User, Workspace
from app.models.enums import TelegramLinkStatus
from app.research.catalog import country_names, industry_label
from app.services import providers as provider_svc

log = logging.getLogger(__name__)
_last_edit: dict[str, float] = {}
EDIT_THROTTLE_SECONDS = 10.0


async def _bot_token(db: AsyncSession, campaign: Campaign) -> str | None:
    creds, _ = await provider_svc.credentials_for(db, campaign.workspace_id, "telegram")
    return creds.get("bot_token")


# Message strings per chat language (the linked account's `locale`, set via the bot's /lang). Kept in step with
# the bot's own cards (telegram/bot/formatting.py): no provider names and no USD costs reach customers.
TEXT: dict[str, dict[str, str]] = {
    "en": {
        "demo": "🧪 Demo search — fictional data",
        "status": "Status",
        "target": "🎯 Target",
        "found": "🔎 Found",
        "qualified": "✅ Qualified",
        "with_contacts": "📞 With contact info",
        "high_priority": "🔥 High priority",
        "emails": "✉️ Business emails",
        "verified": "verified",
        "credits_used": "💳 Credits used",
        "best": "⭐ <b>Best leads</b>",
        "done_completed": "✅ <b>Search completed!</b>",
        "done_partially_completed": "☑️ <b>Search completed (partial)</b>",
        "done_failed": "❌ <b>The search could not finish</b>",
        "done_cancelled": "⏹ <b>Search stopped</b>",
        "done_other": "<b>Search {status}</b>",
        "note_credits": "💳 Stopped early: your credits ran out. Top up to find more.",
        "note_time": "⏱ Stopped at the time limit.",
        "note_partial": "ℹ️ Some sources returned fewer results than usual.",
        "note_failed": "⚠️ Press 🔁 Retry in the bot, or try another city.",
        "btn_best": "⭐ Best leads",
        "btn_results": "📋 All results",
        "btn_csv": "📤 Excel / CSV",
        "btn_progress": "🔄 Refresh",
        "btn_pause": "⏸ Pause",
        "btn_cancel": "⏹ Stop",
        "btn_dashboard": "🌐 Open dashboard",
    },
    "ar": {
        "demo": "🧪 بحث تجريبي — بيانات وهمية",
        "status": "الحالة",
        "target": "🎯 المطلوب",
        "found": "🔎 اتلقى",
        "qualified": "✅ مناسبين",
        "with_contacts": "📞 ليهم بيانات تواصل",
        "high_priority": "🔥 أولوية عالية",
        "emails": "✉️ إيميلات الشركات",
        "verified": "موثّق",
        "credits_used": "💳 الكريدت المستخدم",
        "best": "⭐ <b>أفضل العملاء</b>",
        "done_completed": "✅ <b>البحث خلص!</b>",
        "done_partially_completed": "☑️ <b>البحث خلص جزئياً</b>",
        "done_failed": "❌ <b>البحث ماكملش</b>",
        "done_cancelled": "⏹ <b>البحث اتوقف</b>",
        "done_other": "<b>البحث: {status}</b>",
        "note_credits": "💳 وقف بدري: الرصيد خلص. اشحن عشان تلاقي أكتر.",
        "note_time": "⏱ وقف عند الحد الأقصى للوقت.",
        "note_partial": "ℹ️ بعض المصادر رجّعت نتايج أقل من المعتاد.",
        "note_failed": "⚠️ اضغط 🔁 إعادة في البوت، أو جرّب مدينة تانية.",
        "btn_best": "⭐ أفضل العملاء",
        "btn_results": "📋 كل النتايج",
        "btn_csv": "📤 إكسيل / CSV",
        "btn_progress": "🔄 تحديث",
        "btn_pause": "⏸ إيقاف مؤقت",
        "btn_cancel": "⏹ إيقاف",
        "btn_dashboard": "🌐 لوحة التحكم",
    },
}
STATUS_LABELS = {
    "draft": ("📝", "Draft", "مسودة"),
    "queued": ("⏳", "Starting", "بيبدأ"),
    "discovering": ("🔍", "Finding businesses", "بيدور على الشركات"),
    "enriching": ("📇", "Collecting contacts", "بيجمع بيانات التواصل"),
    "analyzing": ("🤖", "Analysing", "بيحلل"),
    "completed": ("✅", "Completed", "خلص"),
    "partially_completed": ("☑️", "Completed (partial)", "خلص جزئياً"),
    "failed": ("❌", "Failed", "فشل"),
    "paused": ("⏸", "Paused", "متوقف مؤقتاً"),
    "cancelled": ("⏹", "Stopped", "اتوقف"),
}


def _tx(lang: str) -> dict[str, str]:
    return TEXT.get(lang, TEXT["en"])


def _status(value: str, lang: str) -> str:
    row = STATUS_LABELS.get(value)
    if row is None:
        return value.replace("_", " ")
    return row[2] if lang == "ar" else row[1]


def _bar(percent: float | None, width: int = 10) -> str:
    p = max(0, min(100, int(percent or 0)))
    filled = round(p / 100 * width)
    return "▰" * filled + "▱" * (width - filled) + f" {p}%"


def _dot(score: float | None) -> str:
    if score is None:
        return "⚪"
    return "🟢" if score >= 75 else "🟡" if score >= 50 else "🔴"


def _place(c: Campaign, lang: str) -> str:
    names = country_names(c.country)
    country = names[1] if lang == "ar" and len(names) > 1 and names[1] else names[0]
    where = f"{escape(c.city)} · {escape(country)}" if c.city else escape(country)
    return f"📍 {where} · 🏢 {escape(industry_label(c.industry, lang))}"


def _note(c: Campaign, lang: str) -> str | None:
    """Why a run stopped, in customer terms; `last_error` itself names providers and stays internal."""
    x = _tx(lang)
    err = (c.last_error or "").lower()
    if c.status == "failed":
        return x["note_failed"]
    if "credit" in err:
        return x["note_credits"]
    if "runtime" in err:
        return x["note_time"]
    if c.status == "partially_completed":
        return x["note_partial"]
    return None


async def chat_locale(db: AsyncSession, campaign: Campaign) -> str:
    if not campaign.telegram_chat_id:
        return "en"
    locale = await db.scalar(
        select(TelegramAccount.locale).where(TelegramAccount.chat_id == campaign.telegram_chat_id).limit(1)
    )
    return locale if locale in TEXT else "en"


def status_text(c: Campaign, lang: str = "en") -> str:
    x = _tx(lang)
    s = c.stats or {}
    emoji = STATUS_LABELS.get(c.status, ("•",))[0]
    lines = [x["demo"]] if c.is_demo else []
    lines += [
        f"{emoji} <b>{escape(c.name)}</b>",
        _place(c, lang),
        f"{x['status']}: <b>{_status(c.status, lang)}</b>",
        _bar((s.get("progress") or {}).get("percent")),
        f"{x['target']}: {s.get('target', (c.settings or {}).get('target_count', '—'))}",
        f"{x['found']}: {s.get('unique_leads', 0)} · {x['qualified']}: {s.get('qualified', 0)}",
        f"{x['with_contacts']}: {s.get('businesses_with_contacts', 0)}",
    ]
    return "\n".join(lines)


def completion_text(
    c: Campaign, lang: str = "en", credits_used: int | None = None, top: list[tuple[str, float | None]] | None = None
) -> str:
    x = _tx(lang)
    s = c.stats or {}
    title = x.get(f"done_{c.status}") or x["done_other"].format(status=_status(c.status, lang))
    lines = [x["demo"]] if c.is_demo else []
    lines += [
        title,
        f"<b>{escape(c.name)}</b>",
        _place(c, lang),
        "",
        f"{x['target']}: {s.get('target', '—')}",
        f"{x['found']}: {s.get('unique_leads', 0)}",
        f"{x['qualified']}: {s.get('qualified', 0)}",
        f"{x['with_contacts']}: {s.get('businesses_with_contacts', 0)}",
        f"{x['emails']}: {s.get('emails_found', 0)} ({x['verified']}: {s.get('verified_emails', 0)})",
        f"{x['high_priority']}: {s.get('high_priority', 0)}",
    ]
    if credits_used is not None:
        lines.append(f"{x['credits_used']}: {credits_used}")
    if top:
        lines += ["", x["best"]]
        for i, (name, score) in enumerate(top, 1):
            score_txt = f"{score:.0f}/100" if score is not None else "—"
            lines.append(f"{i}. {_dot(score)} {escape(name)} — {score_txt}")
    note = _note(c, lang)
    if note:
        lines += ["", note]
    return "\n".join(lines)


async def completion_extras(db: AsyncSession, c: Campaign) -> tuple[int | None, list[tuple[str, float | None]]]:
    """Credits this campaign used (None for demo or unmetered workspaces) and its three best leads."""
    credits_used = None
    exempt = await db.scalar(select(Workspace.billing_exempt).where(Workspace.id == c.workspace_id))
    if not c.is_demo and not exempt:
        total = await db.scalar(
            select(func.coalesce(func.sum(CampaignLead.credits_charged), 0)).where(CampaignLead.campaign_id == c.id)
        )
        credits_used = int(total or 0)
    rows = (
        await db.execute(
            select(Business.name, CampaignLead.score)
            .join(CampaignLead, CampaignLead.business_id == Business.id)
            .where(CampaignLead.campaign_id == c.id, CampaignLead.score.is_not(None), Business.deleted_at.is_(None))
            .order_by(CampaignLead.score.desc())
            .limit(3)
        )
    ).all()
    return credits_used, [(name, score) for name, score in rows]


def _keyboard(c: Campaign, finished: bool, lang: str = "en") -> dict:
    """Callback data must match the bot's handlers (telegram/bot/handlers/campaigns.py)."""
    x = _tx(lang)
    url = f"{get_settings().frontend_url.rstrip('/')}/app/campaigns/{c.id}"
    cid = str(c.id)
    if finished:
        rows = [
            [
                {"text": x["btn_best"], "callback_data": f"c:top:{cid}"},
                {"text": x["btn_results"], "callback_data": f"c:res:{cid}"},
            ],
            [{"text": x["btn_csv"], "callback_data": f"c:csv:{cid}"}],
        ]
    else:
        rows = [
            [{"text": x["btn_progress"], "callback_data": f"c:prog:{cid}"}],
            [
                {"text": x["btn_pause"], "callback_data": f"c:pause:{cid}"},
                {"text": x["btn_cancel"], "callback_data": f"c:cancel:{cid}"},
            ],
        ]
    if url.startswith("https://"):
        rows.append([{"text": x["btn_dashboard"], "url": url}])
    return {"inline_keyboard": rows}


async def _send(token: str, method: str, payload: dict) -> dict | None:
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(f"https://api.telegram.org/bot{token}/{method}", json=payload)
    if resp.status_code >= 400:
        log.warning("telegram api error", extra={"method": method, "status": resp.status_code, "body": resp.text[:200]})
        return None
    return resp.json().get("result")


async def telegram_progress(db: AsyncSession, campaign: Campaign, force: bool = False) -> None:
    if not campaign.telegram_chat_id:
        return
    key = str(campaign.id)
    if not force and time.monotonic() - _last_edit.get(key, 0) < EDIT_THROTTLE_SECONDS:
        return
    token = await _bot_token(db, campaign)
    if not token:
        return
    _last_edit[key] = time.monotonic()
    lang = await chat_locale(db, campaign)
    text = status_text(campaign, lang)
    if campaign.telegram_status_message_id:
        await _send(
            token,
            "editMessageText",
            {
                "chat_id": campaign.telegram_chat_id,
                "message_id": campaign.telegram_status_message_id,
                "text": text,
                "parse_mode": "HTML",
                "reply_markup": _keyboard(campaign, False, lang),
            },
        )
    else:
        msg = await _send(
            token,
            "sendMessage",
            {
                "chat_id": campaign.telegram_chat_id,
                "text": text,
                "parse_mode": "HTML",
                "reply_markup": _keyboard(campaign, False, lang),
            },
        )
        if msg:
            campaign.telegram_status_message_id = msg.get("message_id")
            await db.commit()


async def notify_platform_admins(db: AsyncSession, text: str) -> int:
    """Telegram message to every platform admin (superuser) with an approved linked account. Best-effort.

    Uses the server's TELEGRAM_BOT_TOKEN, else the Telegram integration of an admin's own workspace.
    Returns how many chats were sent to.
    """
    rows = (
        await db.execute(
            select(TelegramAccount.chat_id, TelegramAccount.workspace_id)
            .join(User, User.id == TelegramAccount.user_id)
            .where(
                User.is_superuser.is_(True),
                User.is_active.is_(True),
                TelegramAccount.status == TelegramLinkStatus.APPROVED,
            )
        )
    ).all()
    if not rows:
        log.info("no platform admin has a linked Telegram account; notification skipped")
        return 0
    token = get_settings().telegram_bot_token
    if not token:
        creds, _ = await provider_svc.credentials_for(db, rows[0].workspace_id, "telegram")
        token = creds.get("bot_token")
    if not token:
        log.info("no Telegram bot token for platform notifications")
        return 0
    sent = 0
    for chat_id, _ in rows:
        try:
            if await _send(token, "sendMessage", {"chat_id": chat_id, "text": text[:4000]}):
                sent += 1
        except httpx.HTTPError as exc:
            log.warning("admin notification failed", extra={"error": str(exc)[:200]})
    return sent


async def notify_campaign_finished(db: AsyncSession, campaign: Campaign) -> None:
    if campaign.telegram_chat_id:
        token = await _bot_token(db, campaign)
        if token:
            lang = await chat_locale(db, campaign)
            credits_used, top = await completion_extras(db, campaign)
            await _send(
                token,
                "sendMessage",
                {
                    "chat_id": campaign.telegram_chat_id,
                    "text": completion_text(campaign, lang, credits_used, top),
                    "parse_mode": "HTML",
                    "reply_markup": _keyboard(campaign, True, lang),
                },
            )
    for key in ("n8n", "crm_webhook"):
        creds, _ = await provider_svc.credentials_for(db, campaign.workspace_id, key)
        url = creds.get("webhook_url")
        if not url:
            continue
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.post(
                    url,
                    json={
                        "event": "campaign.finished",
                        "campaign_id": str(campaign.id),
                        "name": campaign.name,
                        "status": campaign.status,
                        "is_demo": campaign.is_demo,
                        "stats": campaign.stats,
                    },
                )
        except httpx.HTTPError as exc:
            log.warning("webhook failed", extra={"provider": key, "error": str(exc)[:200]})
