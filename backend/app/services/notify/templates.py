"""Notification wording per kind and language, and the shared email layout.

Customer-facing text never names data providers or shows USD costs. Broadcasts (announcement / marketing) carry
their own title and body, written by the admin in both languages.
"""

import html
from string import Formatter

from app.core.config import get_settings

# {kind: {lang: (title, body)}}; placeholders come from the notification's params.
TEXT: dict[str, dict[str, tuple[str, str]]] = {
    "campaign_completed": {
        "en": (
            "Search finished: {name}",
            "{found} businesses found, {qualified} of them a good fit. Open the search to see the best leads.",
        ),
        "ar": (
            "انتهى البحث: {name}",
            "وجدنا {found} نشاطاً تجارياً، منها {qualified} مناسب لك. افتح البحث لترى أفضل العملاء.",
        ),
    },
    "campaign_failed": {
        "en": (
            "Search could not finish: {name}",
            "Try again, or try another city or industry. No credits are charged for leads that were not delivered.",
        ),
        "ar": ("لم يكتمل البحث: {name}", "أعد المحاولة أو جرّب مدينة أو مجالاً آخر. لا يُخصم رصيد عن عملاء لم يصلوك."),
    },
    "credits_low": {
        "en": (
            "Your credits are running low",
            "You have {balance} credits left. Top up so your next search is not cut short.",
        ),
        "ar": ("رصيدك قارب على النفاد", "تبقّى لك {balance} رصيد. اشحن حتى لا يتوقف بحثك القادم في منتصفه."),
    },
    "credits_exhausted": {
        "en": (
            "Your credits ran out",
            'The search "{name}" stopped early because your balance reached zero. Top up to continue finding clients.',
        ),
        "ar": ("نفد رصيدك", 'توقف البحث "{name}" مبكراً لأن رصيدك وصل إلى صفر. اشحن لتكمل البحث عن عملاء.'),
    },
    "credits_added": {
        "en": ("{credits} credits added", "Your balance is now {balance} credits."),
        "ar": ("أُضيف {credits} رصيد", "رصيدك الآن {balance}."),
    },
    "payment_succeeded": {
        "en": (
            "Payment received",
            "We received {amount} {currency} and added {credits} credits to your account. Thank you.",
        ),
        "ar": ("تم استلام الدفع", "استلمنا {amount} {currency} وأضفنا {credits} رصيد إلى حسابك. شكراً لك."),
    },
    "payment_failed": {
        "en": (
            "Payment not completed",
            "Your payment of {amount} {currency} did not go through, and nothing was "
            "charged by us. Try again from the billing page.",
        ),
        "ar": (
            "لم يكتمل الدفع",
            "لم تتم عملية دفع {amount} {currency}، ولم نضف أو نخصم شيئاً. حاول مرة أخرى من صفحة الرصيد.",
        ),
    },
    "topup_approved": {
        "en": ("Top-up approved", "Your transfer was confirmed and {credits} credits were added."),
        "ar": ("تمت الموافقة على الشحن", "تم تأكيد تحويلك وإضافة {credits} رصيد."),
    },
    "topup_rejected": {
        "en": ("Top-up not approved", "We could not confirm your transfer: {reason}"),
        "ar": ("لم تتم الموافقة على الشحن", "لم نتمكن من تأكيد تحويلك: {reason}"),
    },
    "trial_ending": {
        "en": (
            "Your free trial ends in {days} days",
            "Your trial ends on {date}. Top up to keep searching without a break.",
        ),
        "ar": (
            "تنتهي تجربتك المجانية خلال {days} أيام",
            "تنتهي تجربتك في {date}. اشحن رصيدك لتستمر في البحث بدون توقف.",
        ),
    },
    "trial_ended": {
        "en": ("Your free trial has ended", "Top up credits to run new searches. Your leads stay in your account."),
        "ar": ("انتهت تجربتك المجانية", "اشحن رصيداً لتشغيل عمليات بحث جديدة. عملاؤك محفوظون في حسابك."),
    },
    "account_suspended": {
        "en": ("Your account was suspended", "Contact support to find out more or to restore access."),
        "ar": ("تم إيقاف حسابك", "تواصل مع الدعم لمعرفة السبب أو لإعادة التفعيل."),
    },
    "password_changed": {
        "en": ("Your password was changed", "If this wasn't you, reset your password now and contact support."),
        "ar": ("تم تغيير كلمة المرور", "إذا لم تكن أنت، أعد تعيين كلمة المرور فوراً وتواصل مع الدعم."),
    },
    "account_approved": {
        "en": ("Your Rasd account is approved", "Welcome to Rasd! {next_en}"),
        "ar": ("تمت الموافقة على حسابك في رصد", "أهلاً بك في رصد! {next_ar}"),
    },
    "account_rejected": {
        "en": ("Your Rasd account was not approved", "Reason: {reason}\nIf you think this is a mistake, contact us."),
        "ar": ("لم تتم الموافقة على حسابك في رصد", "السبب: {reason}\nإذا كنت ترى أن هذا خطأ فتواصل معنا."),
    },
    "telegram_linked": {
        "en": ("Telegram connected", "Your notifications can now reach you on Telegram{username}."),
        "ar": ("تم ربط تليجرام", "يمكن أن تصلك إشعاراتك الآن على تليجرام{username}."),
    },
    "admin_new_user": {
        "en": ("New signup: {email}", "{name} · {company}"),
        "ar": ("تسجيل جديد: {email}", "{name} · {company}"),
    },
    "admin_signup_review": {
        "en": (
            "New signup to review: {name}",
            "{email} · {phone}\nCompany: {company} · Nationality: {nationality} · IP: {ip}\n"
            "No other account shares their device, phone or email.",
        ),
        "ar": (
            "تسجيل جديد محتاج مراجعة: {name}",
            "{email} · {phone}\nالشركة: {company} · الجنسية: {nationality} · IP: {ip}\n"
            "مفيش حساب تاني بيشاركه نفس الجهاز أو الموبايل أو الإيميل.",
        ),
    },
    "admin_signup_suspicious": {
        "en": (
            "⚠️ Possible duplicate account: {name}",
            "{email} · {phone}\nCompany: {company} · Nationality: {nationality} · IP: {ip}\n"
            "Shares traits with {matches} other account(s):\n{reasons_en}",
        ),
        "ar": (
            "⚠️ حساب مشتبه إنه مكرر: {name}",
            "{email} · {phone}\nالشركة: {company} · الجنسية: {nationality} · IP: {ip}\n"
            "بيشارك بيانات مع {matches} حساب تاني:\n{reasons_ar}",
        ),
    },
    "admin_new_payment": {
        "en": ("Payment: {amount} {currency}", "{workspace} ({email}) bought {credits} credits via {method}."),
        "ar": ("دفع: {amount} {currency}", "{workspace} ({email}) اشترى {credits} رصيد عبر {method}."),
    },
    "admin_topup_request": {
        "en": (
            "Top-up to review: {amount} {currency}",
            "{workspace} ({email}) · {package} ({credits} credits) · {method} · ref {reference}",
        ),
        "ar": (
            "طلب شحن للمراجعة: {amount} {currency}",
            "{workspace} ({email}) · {package} ({credits} رصيد) · {method} · مرجع {reference}",
        ),
    },
    "admin_contact": {
        "en": ("Contact request: {name}", "{company} · {email} · {phone} · {interest}\n{message}"),
        "ar": ("طلب تواصل: {name}", "{company} · {email} · {phone} · {interest}\n{message}"),
    },
    "admin_review": {
        "en": ("New review ({rating}/5) from {author}", "Publish consent: {consent}\n{body}"),
        "ar": ("تقييم جديد ({rating}/5) من {author}", "موافقة على النشر: {consent}\n{body}"),
    },
    "admin_campaign_failed": {
        "en": ("Search failed: {name}", "{workspace}: {error}"),
        "ar": ("فشل بحث: {name}", "{workspace}: {error}"),
    },
    "admin_daily_digest": {
        "en": (
            "Rasd daily summary",
            "Last 24 hours: {new_users} signups, {payments} payments ({revenue} USD), "
            "{campaigns} searches, {failed} failed.",
        ),
        "ar": (
            "ملخص رصد اليومي",
            "آخر 24 ساعة: {new_users} تسجيل، {payments} عملية دفع ({revenue} USD)، {campaigns} بحث، {failed} فشل.",
        ),
    },
}

ACTION = {"en": "Open Rasd", "ar": "افتح رصد"}
FOOTER = {
    "en": "You get this email because of your notification settings in Rasd.",
    "ar": "وصلتك هذه الرسالة حسب إعدادات الإشعارات في حسابك على رصد.",
}
UNSUBSCRIBE = {"en": "Unsubscribe from these emails", "ar": "إلغاء الاشتراك في هذه الرسائل"}
SETTINGS = {"en": "Notification settings", "ar": "إعدادات الإشعارات"}


class _Missing(dict):
    def __missing__(self, key: str) -> str:
        return "—"


def lang_of(locale: str | None) -> str:
    return "ar" if locale == "ar" else "en"


def fill(template: str, params: dict) -> str:
    values = _Missing({k: ("—" if v in (None, "") else v) for k, v in (params or {}).items()})
    try:
        return Formatter().vformat(template, (), values)
    except (ValueError, IndexError):
        return template


def render(kind: str, locale: str | None, params: dict) -> tuple[str, str]:
    """(title, body) for the bell, the email subject and the Telegram message."""
    lang = lang_of(locale)
    if kind in ("announcement", "marketing"):
        p = params or {}
        title = p.get(f"title_{lang}") or p.get("title_ar") or p.get("title_en") or ""
        body = p.get(f"body_{lang}") or p.get("body_ar") or p.get("body_en") or ""
        return title, body
    title, body = TEXT.get(kind, {}).get(lang) or (kind, "")
    return fill(title, params)[:300], fill(body, params)


def absolute(link: str | None) -> str:
    base = get_settings().frontend_url.rstrip("/")
    if not link:
        return f"{base}/app"
    return link if link.startswith("http") else f"{base}{link}"


def email_layout(
    lang: str,
    intro: str,
    *,
    heading: str | None = None,
    action: str | None = None,
    link: str | None = None,
    outro: str | None = None,
    footer: str | None = None,
) -> str:
    """The Rasd email: one card, brand colours, right-to-left in Arabic. Every argument is plain text."""
    direction = "rtl" if lang == "ar" else "ltr"
    parts = [
        f'<!doctype html>\n<html lang="{lang}" dir="{direction}"><body style="margin:0;background:#f7f7f2;'
        'font-family:Arial,sans-serif">',
        '<div style="max-width:520px;margin:24px auto;background:#fff;border-radius:12px;padding:28px;color:#071a17">',
    ]
    if heading:
        parts.append(f'<h1 style="font-size:18px;margin:0 0 14px">{html.escape(heading)}</h1>')
    paragraphs = "".join(
        f'<p style="font-size:15px;line-height:1.6;margin:0 0 10px">{html.escape(line)}</p>'
        for line in intro.split("\n")
        if line.strip()
    )
    parts.append(paragraphs)
    if action and link:
        parts.append(
            f'<p style="margin:28px 0"><a href="{html.escape(link)}" style="background:#071a17;color:#c8f169;'
            f'padding:12px 22px;border-radius:8px;text-decoration:none;font-weight:bold">{html.escape(action)}</a></p>'
        )
    if outro:
        parts.append(f'<p style="font-size:13px;line-height:1.6;color:#4b5f58">{html.escape(outro)}</p>')
    if link and action:
        parts.append(f'<p style="font-size:12px;color:#6f8a82;word-break:break-all">{html.escape(link)}</p>')
    parts.append('<p style="font-size:12px;color:#6f8a82">رصد · Rasd</p>')
    if footer:
        parts.append(f'<p style="font-size:11px;color:#8aa39b;line-height:1.6">{footer}</p>')
    parts.append("</div></body></html>")
    return "\n".join(parts)


def render_email(
    kind: str, locale: str | None, title: str, body: str, link: str | None, unsubscribe_url: str | None
) -> tuple[str, str, str]:
    """(subject, text, html) of a notification email."""
    lang = lang_of(locale)
    url = absolute(link)
    settings_url = absolute("/app/settings?tab=notifications")
    footer_html = (
        f'{html.escape(FOOTER[lang])} <a href="{html.escape(settings_url)}" style="color:#6f8a82">'
        f"{html.escape(SETTINGS[lang])}</a>"
    )
    footer_text = f"{FOOTER[lang]} {SETTINGS[lang]}: {settings_url}"
    if unsubscribe_url:
        footer_html += (
            f' · <a href="{html.escape(unsubscribe_url)}" style="color:#6f8a82">{html.escape(UNSUBSCRIBE[lang])}</a>'
        )
        footer_text += f"\n{UNSUBSCRIBE[lang]}: {unsubscribe_url}"
    page = email_layout(lang, body, heading=title, action=ACTION[lang], link=url, footer=footer_html)
    text = f"{title}\n\n{body}\n\n{ACTION[lang]}:\n{url}\n\nرصد · Rasd\n\n{footer_text}"
    return title, text, page


REVIEW_BUTTONS = {
    "en": {"ok": "✅ Approve", "no": "❌ Reject", "info": "🔎 Details"},
    "ar": {"ok": "✅ قبول", "no": "❌ رفض", "info": "🔎 التفاصيل"},
}


def telegram_buttons(kind: str, locale: str | None, params: dict) -> dict | None:
    """Inline keyboard under the Telegram message; the bot handles the callbacks (telegram/bot/handlers/admin.py)."""
    if kind in ("admin_signup_review", "admin_signup_suspicious") and params.get("user_id"):
        b, uid = REVIEW_BUTTONS[lang_of(locale)], params["user_id"]
        return {
            "inline_keyboard": [
                [
                    {"text": b["ok"], "callback_data": f"adm:ok:{uid}"},
                    {"text": b["no"], "callback_data": f"adm:no:{uid}"},
                ],
                [{"text": b["info"], "callback_data": f"adm:u:{uid}"}],
            ]
        }
    return None


def render_telegram(title: str, body: str, link: str | None) -> str:
    """HTML parse mode message. Trimmed before escaping: cutting the escaped text could split an entity like &amp;
    and Telegram rejects the whole message (its limit is 4096 characters)."""
    title, body = title[:300], body if len(body) <= 3500 else body[:3499] + "…"
    text = f"<b>{html.escape(title)}</b>"
    if body:
        text += f"\n\n{html.escape(body)}"
    if link:
        text += f'\n\n<a href="{html.escape(absolute(link))}">Rasd ↗</a>'
    return text
