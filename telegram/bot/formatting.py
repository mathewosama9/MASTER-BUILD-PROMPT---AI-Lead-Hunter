"""Plain-text renderers. All numbers come straight from backend campaign records."""
from html import escape

STATUS_EMOJI = {
    "draft": "📝", "queued": "⏳", "discovering": "🔍", "enriching": "📇", "analyzing": "🤖", "completed": "✅",
    "partially_completed": "⚠️", "failed": "❌", "paused": "⏸", "cancelled": "✖",
}


def campaign_card(c: dict) -> str:
    s = c.get("stats") or {}
    pct = (s.get("progress") or {}).get("percent")
    demo = "🧪 DEMO MODE — fictional data\n" if c.get("is_demo") else ""
    lines = [
        f"{demo}{STATUS_EMOJI.get(c['status'], '•')} <b>{escape(c['name'])}</b>",
        f"Country: {c['country']}" + (f" · City: {escape(c['city'])}" if c.get("city") else ""),
        f"Industry: {escape(c['industry'])}",
        f"Status: {c['status'].replace('_', ' ').title()} ({c.get('stage', '').replace('_', ' ')})",
        f"Target: {s.get('target', (c.get('settings') or {}).get('target_count', '—'))}",
        f"Discovered: {s.get('discovered', 0)} · Unique: {s.get('unique_leads', 0)}",
        f"Enriched: {s.get('enriched', 0)} · Analyzed: {s.get('analyzed', 0)}",
        f"Qualified: {s.get('qualified', 0)} · High priority: {s.get('high_priority', 0)}",
        f"Emails found: {s.get('emails_found', 0)} · Verified: {s.get('verified_emails', 0)}",
        "Progress: " + (f"{pct}%" if pct is not None else "calculating…"),
        f"Cost: ${(c.get('cost_discovery') or 0) + (c.get('cost_ai') or 0):.2f}",
    ]
    if c.get("last_error"):
        lines.append(f"Notes: {escape(c['last_error'][:200])}")
    return "\n".join(lines)


def leads_list(items: list[dict], title: str) -> str:
    if not items:
        return title + "\n\n—"
    rows = [f"<b>{escape(title)}</b>"]
    for i, x in enumerate(items, 1):
        score = f"{x['latest_score']:.0f}" if x.get("latest_score") is not None else "—"
        contact = "📞" if x.get("contact_count") else "Not found"
        demo = " 🧪" if x.get("is_demo") else ""
        rows.append(f"{i}. <b>{escape(x['name'])}</b>{demo} — {score}/100 · {x.get('latest_priority') or '—'}\n"
                    f"   {escape(x.get('city') or '')} · {escape(x.get('website_url') or 'no website')} · {contact}")
    return "\n".join(rows)
