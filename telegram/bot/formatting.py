"""HTML renderers. Numbers come straight from backend records; source names and USD costs are never shown."""
import re
from html import escape

from bot.i18n import CRM, PRIORITY, STATUS, label, num, t

MAX_TEXT = 4000


def country_name(meta: dict | None, code: str | None, lang: str) -> str:
    c = next((x for x in (meta or {}).get("countries", []) if x["code"] == code), None)
    if c is None:
        return code or "—"
    return c["name_ar"] if lang == "ar" else c["name_en"]


def industry_name(meta: dict | None, key: str | None, lang: str) -> str:
    i = next((x for x in (meta or {}).get("industries", []) if x["key"] == key), None)
    if i is None:
        return (key or "—").replace("_", " ")
    return i["ar"] if lang == "ar" else i["en"]


def bar(percent: float | None, width: int = 10) -> str:
    p = max(0, min(100, int(percent or 0)))
    filled = round(p / 100 * width)
    return "▰" * filled + "▱" * (width - filled) + f" {p}%"


def score_dot(score: float | None) -> str:
    if score is None:
        return "⚪"
    return "🟢" if score >= 75 else "🟡" if score >= 50 else "🔴"


def run_note(c: dict, lang: str) -> str | None:
    """A customer-friendly line for why a run stopped; internal errors (with provider names) stay hidden."""
    err = (c.get("last_error") or "").lower()
    if c["status"] == "failed":
        return t("c_note_failed", lang)
    if "credit" in err:
        return t("c_note_credits", lang)
    if "runtime" in err:
        return t("c_note_time", lang)
    if c["status"] == "partially_completed":
        return t("c_note_partial", lang)
    return None


def campaign_card(c: dict, lang: str, meta: dict | None = None) -> str:
    s = c.get("stats") or {}
    place = escape(c.get("city") or country_name(meta, c.get("country"), lang))
    if c.get("city"):
        place += f" · {escape(country_name(meta, c.get('country'), lang))}"
    lines = []
    if c.get("is_demo"):
        lines.append(t("demo_search", lang))
    lines += [
        f"{STATUS.get(c['status'], ('•',))[0]} <b>{escape(c['name'])}</b>",
        t("c_place", lang, place=place) + f" · 🏢 {escape(industry_name(meta, c.get('industry'), lang))}",
        t("c_status", lang, status=label(STATUS, c["status"], lang, emoji=False)),
    ]
    pct = (s.get("progress") or {}).get("percent")
    if c["status"] in ("queued", "discovering", "enriching", "analyzing", "paused"):
        lines.append(bar(pct))
    target = s.get("target", (c.get("settings") or {}).get("target_count"))
    lines += [
        t("c_target", lang, n=num(target)),
        t("c_found", lang, found=num(s.get("unique_leads", 0)), qualified=num(s.get("qualified", 0))),
        t("c_contacts", lang, n=num(s.get("businesses_with_contacts", 0)), h=num(s.get("high_priority", 0))),
    ]
    note = run_note(c, lang)
    if note:
        lines += ["", note]
    return "\n".join(lines)


def campaigns_list(items: list[dict], total: int, lang: str) -> str:
    rows = [t("campaigns_title", lang, total=num(total)), ""]
    for i, c in enumerate(items, 1):
        s = c.get("stats") or {}
        emoji = STATUS.get(c["status"], ("•",))[0]
        if c["status"] in ("queued", "discovering", "enriching", "analyzing"):
            detail = f"{(s.get('progress') or {}).get('percent') or 0}%"
        else:
            detail = f"✅ {num(s.get('qualified', 0))}"
        rows.append(f"{i}. {emoji} <b>{escape(c['name'])}</b> — {detail}")
    return "\n".join(rows)


def leads_page(items: list[dict], total: int, page: int, page_size: int, lang: str, qualified: bool) -> str:
    title = t("leads_top" if qualified else "leads_all", lang)
    a = (page - 1) * page_size + 1
    rows = [f"{title} · {t('leads_range', lang, a=a, b=a + len(items) - 1, total=num(total))}", ""]
    for i, x in enumerate(items, 1):
        score = x.get("latest_score")
        score_txt = f"{score:.0f}/100" if score is not None else "—"
        contact = t("contacts_n", lang, n=x["contact_count"]) if x.get("contact_count") else t("no_contact", lang)
        if x.get("has_verified_contact"):
            contact += " ✔️"
        demo = " 🧪" if x.get("is_demo") else ""
        where = escape(x.get("city") or "")
        rows.append(f"{i}. {score_dot(score)} <b>{escape(x['name'])}</b>{demo} — {score_txt}\n"
                    f"     {'📍 ' + where + ' · ' if where else ''}{contact}")
    rows += ["", t("leads_pick", lang)]
    return "\n".join(rows)


CONTACT_ICONS = {"phone": "📞", "whatsapp": "💬", "email": "✉️", "social": "🔗", "person": "👤",
                 "contact_page": "📄"}


def whatsapp_number(contacts: list[dict]) -> str | None:
    """Digits for a wa.me link: a WhatsApp contact first, else an international-format phone."""
    for kind in ("whatsapp", "phone"):
        for c in contacts:
            if c["type"] != kind or c.get("is_suppressed") or c.get("verification_status") == "invalid":
                continue
            value = c["value"].strip()
            if kind == "phone" and not value.startswith(("+", "00")):
                continue  # local numbers cannot be turned into a wa.me link safely
            digits = re.sub(r"\D", "", value).removeprefix("00")
            if 8 <= len(digits) <= 15:
                return digits
    return None


def lead_card(d: dict, lang: str, meta: dict | None = None) -> str:
    b = d["business"]
    a = d.get("assessment") or {}
    score = b.get("latest_score")
    lines = [f"{score_dot(score)} <b>{escape(b['name'])}</b>" + (" 🧪" if b.get("is_demo") else "")]
    where = " · ".join(escape(x) for x in (b.get("city"), country_name(meta, b.get("country"), lang)) if x)
    lines.append(f"🏢 {escape(industry_name(meta, b.get('industry'), lang))}" + (f" · 📍 {where}" if where else ""))
    if score is not None:
        prio = label(PRIORITY, b.get("latest_priority"), lang, emoji=False) if b.get("latest_priority") else "—"
        lines.append(t("l_score", lang, score=f"{score:.0f}", priority=prio))
    lines.append(t("l_crm", lang, status=label(CRM, b.get("crm_status"), lang)))
    if d.get("suppressed"):
        lines.append(t("l_suppressed", lang))
    if a.get("opportunity"):
        lines += ["", t("l_why", lang), escape(a["opportunity"][:500])]
    elif a.get("summary"):
        lines += ["", t("l_summary", lang), escape(a["summary"][:500])]
    lines += ["", t("l_contacts", lang)]
    shown: dict[str, int] = {}
    for c in d.get("contacts", []):
        kind = c["type"]
        if kind not in CONTACT_ICONS or shown.get(kind, 0) >= 3 or c.get("verification_status") == "invalid":
            continue
        shown[kind] = shown.get(kind, 0) + 1
        value = escape(c["value"])
        if kind in ("phone", "whatsapp", "email"):
            value = f"<code>{value}</code>"
        if kind == "person":
            value = escape(" — ".join(x for x in (c.get("person_name"), c.get("person_role")) if x) or c["value"])
        mark = f" ✔️ {t('verified', lang)}" if c.get("verification_status") == "verified" else ""
        mark += " 🚫" if c.get("is_suppressed") else ""
        lines.append(f"{CONTACT_ICONS[kind]} {value}{mark}")
    if not shown:
        lines.append(t("l_no_contacts", lang))
    if b.get("website_url"):
        lines.append(f"🌐 {escape(b['website_url'])}")
    if d.get("notes"):
        lines += ["", t("l_note", lang, note=escape(d["notes"][0]["body"][:300]))]
    return "\n".join(lines)[:MAX_TEXT]


def balance_card(s: dict, lang: str) -> str:
    lines = [t("bal_title", lang), ""]
    if s.get("billing_exempt"):
        lines.append(t("bal_unlimited", lang))
        return "\n".join(lines)
    lines.append(t("bal_value", lang, n=num(s.get("balance", 0))))
    if s.get("trial_expired"):
        lines.append(t("bal_trial_expired", lang))
    elif s.get("on_trial") and s.get("trial_days_left") is not None:
        lines.append(t("bal_trial", lang, days=s["trial_days_left"]))
    if s.get("awaiting_verification"):
        lines.append(t("bal_unverified", lang))
    if s.get("low_balance"):
        lines.append(t("bal_low", lang))
    if s.get("pending_topups"):
        lines.append(t("bal_pending", lang, n=s["pending_topups"]))
    lines += ["", f"<i>{t('bal_rule', lang)}</i>"]
    return "\n".join(lines)


def summary_card(data: dict, estimate: dict | None, lang: str, meta: dict | None) -> str:
    industry = data.get("industry_label") or industry_name(meta, data.get("industry"), lang)
    lines = [t("summary", lang), ""]
    if data.get("sources") == ["demo"]:
        lines += [t("demo_search", lang), ""]
    lines += [
        f"{t('f_country', lang)}: {escape(country_name(meta, data.get('country'), lang))}",
        f"{t('f_city', lang)}: {escape(data.get('city_label') or data.get('city') or t('all_cities', lang))}",
        f"{t('f_industry', lang)}: {escape(industry)}",
        f"{t('f_count', lang)}: {t('count_value', lang, n=num(data.get('count')))}",
        f"{t('f_ai', lang)}: {t('on' if data.get('ai', True) else 'off', lang)}",
    ]
    if data.get("keywords"):
        sep = "، " if lang == "ar" else ", "
        lines.append(f"{t('f_keywords', lang)}: {escape(sep.join(data['keywords'][:6]))}")
    if not data.get("sources"):
        lines += ["", t("no_sources", lang)]
    elif estimate and estimate.get("credit_balance") is not None and data.get("sources") != ["demo"]:
        balance = estimate["credit_balance"]
        lines += ["", t("credits_line", lang, max=num(estimate.get("credits_max", 0)), balance=num(balance)),
                  f"<i>{t('credits_rule', lang)}</i>"]
        if balance <= 0:
            lines.append(t("credits_zero", lang))
        elif balance < estimate.get("credits_max", 0):
            lines.append(t("credits_low", lang))
    return "\n".join(lines)
