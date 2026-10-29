"""Outbound notifications for campaign lifecycle.

Telegram messages are sent with the Bot API directly from the worker so notifications work even when the
bot process restarts. Numbers always come from the stored campaign stats.
"""

import logging
import time

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import Campaign, TelegramAccount
from app.research.catalog import country_names, industry_label
from app.services import providers as provider_svc

log = logging.getLogger(__name__)
_last_edit: dict[str, float] = {}
EDIT_THROTTLE_SECONDS = 10.0


async def _bot_token(db: AsyncSession, campaign: Campaign) -> str | None:
    creds, _ = await provider_svc.credentials_for(db, campaign.workspace_id, "telegram")
    return creds.get("bot_token")


# Message strings per chat language (the linked account's `locale`, set via the bot's /lang).
TEXT: dict[str, dict[str, str]] = {
    "en": {
        "demo": "🧪 DEMO MODE",
        "demo_long": "🧪 DEMO MODE — fictional data",
        "country": "Country",
        "industry": "Industry",
        "status": "Status",
        "target": "Target",
        "discovered": "Discovered",
        "unique": "Unique",
        "enriched": "Enriched",
        "analyzed": "Analyzed",
        "qualified": "Qualified",
        "progress": "Progress",
        "calculating": "calculating…",
        "cost": "Cost",
        "done_completed": "✅ Research completed!",
        "done_partially_completed": "⚠️ Research partially completed",
        "done_failed": "❌ Research failed",
        "done_other": "Research {status}",
        "campaign": "Campaign",
        "businesses_discovered": "Businesses discovered",
        "unique_saved": "Unique businesses saved",
        "unique_qualified": "Unique qualified leads",
        "emails_found": "Business emails found",
        "verified_emails": "Verified emails",
        "high_priority": "High-priority leads",
        "total_cost": "Total cost",
        "notes": "Notes",
        "btn_results": "📋 View Results",
        "btn_csv": "📤 Export CSV",
        "btn_top": "🏆 Top 10 Leads",
        "btn_progress": "🔄 View Progress",
        "btn_pause": "⏸ Pause",
        "btn_cancel": "✖ Cancel",
        "btn_dashboard": "🌐 Open Dashboard",
    },
    "ar": {
        "demo": "🧪 وضع تجريبي",
        "demo_long": "🧪 وضع تجريبي — بيانات وهمية",
        "country": "الدولة",
        "industry": "المجال",
        "status": "الحالة",
        "target": "المستهدف",
        "discovered": "المكتشف",
        "unique": "الفريد",
        "enriched": "تم إثراؤه",
        "analyzed": "تم تحليله",
        "qualified": "المؤهل",
        "progress": "التقدم",
        "calculating": "جارٍ الحساب…",
        "cost": "التكلفة",
        "done_completed": "✅ اكتمل البحث!",
        "done_partially_completed": "⚠️ اكتمل البحث جزئياً",
        "done_failed": "❌ فشل البحث",
        "done_other": "البحث: {status}",
        "campaign": "الحملة",
        "businesses_discovered": "الشركات المكتشفة",
        "unique_saved": "الشركات الفريدة المحفوظة",
        "unique_qualified": "العملاء المؤهلون",
        "emails_found": "إيميلات الشركات",
        "verified_emails": "الإيميلات الموثقة",
        "high_priority": "عملاء أولوية عالية",
        "total_cost": "إجمالي التكلفة",
        "notes": "ملاحظات",
        "btn_results": "📋 عرض النتائج",
        "btn_csv": "📤 تصدير CSV",
        "btn_top": "🏆 أفضل 10 عملاء",
        "btn_progress": "🔄 عرض التقدم",
        "btn_pause": "⏸ إيقاف مؤقت",
        "btn_cancel": "✖ إلغاء",
        "btn_dashboard": "🌐 فتح لوحة التحكم",
    },
}
STATUS_AR = {
    "draft": "مسودة",
    "queued": "في الانتظار",
    "discovering": "جارٍ الاكتشاف",
    "enriching": "جارٍ الإثراء",
    "analyzing": "جارٍ التحليل",
    "completed": "مكتملة",
    "partially_completed": "مكتملة جزئياً",
    "failed": "فشلت",
    "paused": "متوقفة مؤقتاً",
    "cancelled": "ملغاة",
}


def _tx(lang: str) -> dict[str, str]:
    return TEXT.get(lang, TEXT["en"])


def _status(value: str, lang: str) -> str:
    return STATUS_AR.get(value, value) if lang == "ar" else value.replace("_", " ").title()


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
    p = (s.get("progress") or {}).get("percent")
    names = country_names(c.country)
    country = names[1] if lang == "ar" and len(names) > 1 and names[1] else names[0]
    lines = [
        (f"{x['demo']}\n" if c.is_demo else "") + f"📊 {c.name}",
        f"{x['country']}: {country}" + (f" · {c.city}" if c.city else ""),
        f"{x['industry']}: {industry_label(c.industry, lang)}",
        f"{x['status']}: {_status(c.status, lang)}",
        f"{x['target']}: {s.get('target', (c.settings or {}).get('target_count', '—'))}",
        f"{x['discovered']}: {s.get('discovered', 0)} · {x['unique']}: {s.get('unique_leads', 0)}",
        f"{x['enriched']}: {s.get('enriched', 0)} · {x['analyzed']}: {s.get('analyzed', 0)} · "
        f"{x['qualified']}: {s.get('qualified', 0)}",
        f"{x['progress']}: {p}%" if p is not None else f"{x['progress']}: {x['calculating']}",
        f"{x['cost']}: ${c.cost_discovery + c.cost_ai:.2f}",
    ]
    return "\n".join(lines)


def completion_text(c: Campaign, lang: str = "en") -> str:
    x = _tx(lang)
    s = c.stats or {}
    title = x.get(f"done_{c.status}") or x["done_other"].format(status=_status(c.status, lang))
    lines = [
        (f"{x['demo_long']}\n" if c.is_demo else "") + title,
        f"{x['campaign']}: {c.name}",
        "",
        f"{x['target']}: {s.get('target', '—')}",
        f"{x['businesses_discovered']}: {s.get('discovered', 0)}",
        f"{x['unique_saved']}: {s.get('unique_leads', 0)}",
        f"{x['unique_qualified']}: {s.get('qualified', 0)}",
        f"{x['emails_found']}: {s.get('emails_found', 0)}",
        f"{x['verified_emails']}: {s.get('verified_emails', 0)}",
        f"{x['high_priority']}: {s.get('high_priority', 0)}",
        f"{x['total_cost']}: ${c.cost_discovery + c.cost_ai:.2f}",
    ]
    if c.last_error:
        lines += ["", f"{x['notes']}: {c.last_error[:300]}"]
    return "\n".join(lines)


def _keyboard(c: Campaign, finished: bool, lang: str = "en") -> dict:
    x = _tx(lang)
    url = f"{get_settings().frontend_url}/campaigns/{c.id}"
    cid = str(c.id)
    if finished:
        rows = [
            [
                {"text": x["btn_results"], "callback_data": f"c:res:{cid}"},
                {"text": x["btn_csv"], "callback_data": f"c:csv:{cid}"},
            ],
            [{"text": x["btn_top"], "callback_data": f"c:top:{cid}"}],
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
                "reply_markup": _keyboard(campaign, False, lang),
            },
        )
    else:
        msg = await _send(
            token,
            "sendMessage",
            {"chat_id": campaign.telegram_chat_id, "text": text, "reply_markup": _keyboard(campaign, False, lang)},
        )
        if msg:
            campaign.telegram_status_message_id = msg.get("message_id")
            await db.commit()


async def notify_campaign_finished(db: AsyncSession, campaign: Campaign) -> None:
    if campaign.telegram_chat_id:
        token = await _bot_token(db, campaign)
        if token:
            lang = await chat_locale(db, campaign)
            await _send(
                token,
                "sendMessage",
                {
                    "chat_id": campaign.telegram_chat_id,
                    "text": completion_text(campaign, lang),
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
