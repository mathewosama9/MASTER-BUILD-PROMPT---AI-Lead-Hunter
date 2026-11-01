"""Rule-based analyzer used in DEMO MODE and when no AI provider is configured.

It is labelled `provider="demo"` or `provider="heuristic"` in stored assessments so it is never mistaken for
AI output. It reasons only from observed website signals, with the same observed/hypothesis/unknown split.
"""

from app.research.analysis.schemas import BusinessAnalysis, Hypothesis, ObservedSignal, ServiceRecommendation
from app.research.catalog import INDUSTRIES
from app.research.catalog import LEGACY_SERVICES as SERVICES

APPOINTMENT_INDUSTRIES = {"dental_clinics", "medical_clinics", "beauty_salons", "fitness", "legal", "automotive"}

# The kind of need each observed-signal rule points to, as words an offering's name/description/keywords would use.
# The rule-based analyzer recommends the seller's own offering that matches a need best; nothing else.
NEED_WORDS: dict[str, list[str]] = {
    "appointment_automation": ["booking", "appointment", "schedul", "reservation", "calendar", "حجز", "مواعيد", "موعد"],
    "whatsapp_automation": ["whatsapp", "chatbot", "bot", "auto-reply", "واتساب", "بوت", "رد آلي", "الرد الآلي"],
    "lead_management": ["lead", "sales", "pipeline", "follow-up", "مبيعات", "عملاء محتملين", "متابعة"],
    "crm_integration": ["crm", "customer data", "integration", "erp", "أنظمة", "تكامل", "إدارة العملاء"],
    "ai_support_agent": ["support", "customer service", "chat", "call center", "خدمة العملاء", "دعم", "شات"],
    "ai_sales_assistant": ["sales assistant", "conversion", "upsell", "store", "مساعد مبيعات", "تحويل"],
    "ecommerce_development": ["e-commerce", "ecommerce", "online store", "shop", "checkout", "متجر", "تجارة إلكترونية"],
    "website_development": ["website", "web", "landing", "seo", "design", "موقع", "مواقع", "تصميم", "سيو"],
    "process_automation": ["automation", "workflow", "process", "أتمتة", "سير العمل"],
    "n8n_automation": ["n8n", "automation", "workflow", "أتمتة"],
}


def _fold(text: str) -> str:
    return (text or "").casefold()


def resolve_offering(key: str, offerings: list[dict]) -> dict | None:
    """The seller's offering for a need: the same id (legacy workspaces), else the best keyword match."""
    for o in offerings:
        if o.get("id") == key:
            return o
    words = NEED_WORDS.get(key, [])
    best, best_hits = None, 0
    for o in offerings:
        hay = _fold(" ".join([o.get("name", ""), o.get("description", ""), " ".join(o.get("keywords") or [])]))
        hits = sum(1 for w in words if w in hay)
        if hits > best_hits:
            best, best_hits = o, hits
    return best


def heuristic_analysis(
    *, business: dict, evidence: list[dict], target: dict, seller: dict | None = None
) -> BusinessAnalysis:
    sig = {e["signal"]: e for e in evidence if e.get("signal")}
    observed = {k for k, e in sig.items() if e.get("observed")}
    not_observed = {k for k, e in sig.items() if not e.get("observed")}
    page_ids = [e["id"] for e in evidence if e.get("kind") == "page"]
    industry = target.get("industry") or business.get("industry") or ""
    wanted = set(target.get("services") or [])

    signals = [
        ObservedSignal(signal=f"{sig[k]['label']} observed", evidence_ids=[sig[k]["id"]]) for k in sorted(observed)
    ]
    hypotheses: list[Hypothesis] = []
    problems: list[str] = []
    recs: list[tuple[str, str, list[str], float]] = []
    unknowns: list[str] = []

    def ids(*keys: str) -> list[str]:
        return [sig[k]["id"] for k in keys if k in sig]

    if industry in APPOINTMENT_INDUSTRIES:
        if "online_booking" in observed:
            hypotheses.append(
                Hypothesis(
                    statement="Bookings may already be partly digital; reminders and follow-ups could still be manual.",
                    basis_evidence_ids=ids("online_booking"),
                    confidence="low",
                )
            )
            recs.append(
                (
                    "ai_support_agent",
                    "Booking flow exists; an assistant could answer pre-booking questions.",
                    ids("online_booking"),
                    0.5,
                )
            )
        else:
            problems.append("Appointments may be handled by phone or messaging, which can be time-consuming.")
            unknowns.append("Whether an online booking system exists outside the inspected pages.")
            recs.append(
                (
                    "appointment_automation",
                    "No online booking page was observed on the inspected pages.",
                    ids("online_booking") or page_ids[:1],
                    0.8,
                )
            )
    if "whatsapp_link" in observed:
        hypotheses.append(
            Hypothesis(
                statement="Customer enquiries likely arrive via WhatsApp and may be answered manually.",
                basis_evidence_ids=ids("whatsapp_link"),
                confidence="medium",
            )
        )
        recs.append(
            (
                "whatsapp_automation",
                "A WhatsApp click-to-chat link is published on the website.",
                ids("whatsapp_link"),
                0.75,
            )
        )
    if "contact_form" in observed and "crm_forms" not in observed:
        unknowns.append("Whether contact-form enquiries are routed to a CRM.")
        recs.append(
            (
                "lead_management",
                "A contact form was observed; routing/qualification is not visible.",
                ids("contact_form"),
                0.6,
            )
        )
        recs.append(
            (
                "crm_integration",
                "Lead capture exists; no CRM form embed was observed.",
                ids("contact_form", "crm_forms"),
                0.45,
            )
        )
    if "live_chat" not in observed and "chatbot" not in observed:
        unknowns.append("Whether the business offers chat support on other channels.")
        recs.append(
            (
                "ai_support_agent",
                "No live chat or chatbot widget was observed on the inspected pages.",
                ids("live_chat", "chatbot"),
                0.55,
            )
        )
    if industry == "ecommerce" or "ecommerce" in observed:
        recs.append(
            (
                "ai_sales_assistant",
                "Online store signals observed; a sales assistant could support buyers.",
                ids("ecommerce"),
                0.55,
            )
        )
    elif industry in {"restaurants", "beauty_salons"} and "ecommerce" in not_observed:
        recs.append(
            (
                "ecommerce_development",
                "No online ordering/checkout was observed on the inspected pages.",
                ids("ecommerce"),
                0.4,
            )
        )
    if "mobile_viewport" in not_observed or "https" in not_observed:
        problems.append("Website basics (HTTPS / mobile viewport) were not observed.")
        recs.append(
            (
                "website_development",
                "Basic website capabilities were not observed.",
                ids("mobile_viewport", "https"),
                0.5,
            )
        )
    if not evidence:
        unknowns.append("The website could not be inspected; no evidence is available.")

    # Recommend what this seller sells: each need maps to the seller's matching offering (none = not recommended).
    offerings = (seller or {}).get("offerings") or []
    mapped: list[tuple[str, str, str, list[str], float]] = []
    for key, why, ev, weight in recs:
        if offerings:
            o = resolve_offering(key, offerings)
            if o is None:
                continue
            mapped.append((o["id"], o.get("name", ""), why, ev, weight))
        else:  # no profile yet: the legacy service labels
            mapped.append((key, SERVICES.get(key, {}).get("en", key), why, ev, weight))
    mapped.sort(key=lambda r: (r[0] in wanted, r[4]), reverse=True)
    seen: set[str] = set()
    final: list[ServiceRecommendation] = []
    for oid, name, why, ev, _ in mapped:
        if oid in seen:
            continue
        seen.add(oid)
        final.append(ServiceRecommendation(service=oid, name=name, rationale=why, evidence_ids=[e for e in ev if e]))
        if len(final) == 3:
            break

    observed_count = len(observed)
    # Industry fit is grounded in page text: do the inspected pages mention the target industry's terms?
    page_text = " ".join(str(e.get("excerpt") or "") + " " + str(e.get("title") or "") for e in evidence).lower()
    terms = INDUSTRIES.get(industry, {}).get("terms_en", []) + INDUSTRIES.get(industry, {}).get("terms_ar", [])
    term_hits = sum(1 for t in terms if any(w in page_text for w in t.lower().split() if len(w) > 3))
    industry_fit = 0.85 if term_hits >= 2 else 0.65 if term_hits == 1 else (0.4 if evidence else 0.3)
    chars = target.get("characteristics") or []
    text = " ".join(str(e.get("excerpt") or "") for e in evidence).lower()
    char_hits = sum(1 for c in chars if c and c.lower() in text)
    characteristics_fit = (char_hits / len(chars)) if chars else 0.5
    confidence = min(0.25 + 0.06 * observed_count + 0.05 * len(page_ids), 0.8) if evidence else 0.1
    name = business.get("name") or "This business"
    top = (final[0].name or final[0].service) if final else None
    summary = (business.get("description") or f"{name} operates in {industry.replace('_', ' ')}.")[:400]
    return BusinessAnalysis(
        business_summary=summary,
        observed_signals=signals,
        hypotheses=hypotheses,
        potential_problems=problems,
        recommended_services=final,
        opportunity=(
            f"Based on observed website signals, {name} may benefit from {top}."
            if top
            else "Not enough evidence to identify a clear opportunity."
        ),
        suggested_pitch=(
            f"I looked at {name}'s website and noticed {final[0].rationale[0].lower()}"
            f"{final[0].rationale[1:]} We help similar businesses with {top}."
            if final
            else ""
        ),
        unknowns=unknowns,
        confidence=round(confidence, 2),
        industry_fit=industry_fit,
        characteristics_fit=round(characteristics_fit, 2),
    )


def template_pitch(context: dict, language: str) -> dict[str, str]:
    """Non-AI fallback drafts built only from stored facts. Clearly generic; for human editing."""
    name = context.get("company") or "your team"
    service_key = context.get("service") or ""
    service = (
        context.get("service_name")
        or SERVICES.get(service_key, {}).get("ar" if language == "ar" else "en")
        or service_key
        or ("خدماتنا" if language == "ar" else "our services")
    )
    obs = (context.get("observations") or [None])[0]
    if language == "ar" and (context.get("country") or "").upper() == "EG":
        obs_line = f"لاحظنا في موقعكم: {obs}." if obs else ""
        return {
            "short_intro": f"أهلاً بفريق {name}، إحنا بنساعد شركات زيكم في {service}.",
            "email_subject": f"فكرة بخصوص {service} لـ {name}",
            "email_body": (
                f"أهلاً بفريق {name}،\n\n{obs_line}\nإحنا بنساعد شركات شبهكم في {service} "
                "بطريقة تمشي مع شغلكم الحالي. ممكن نتكلم 15 دقيقة نفهم احتياجاتكم؟\n\nمع خالص التحية\n\n"
                'لو حضرتك مش حابب توصلك رسايل مننا، رد بكلمة "إلغاء".'
            ),
            "whatsapp_message": (
                f"أهلاً بفريق {name} 👋 {obs_line} إحنا بنقدم {service}. ينفع نتكلم دقيقتين؟ (للإلغاء ابعت: إلغاء)"
            ),
            "follow_up": f"بتابع مع حضرتك رسالتي اللي فاتت بخصوص {service}. ينفع نتكلم الأسبوع ده؟",
            "proposal_summary": f"مقترح مبدئي: نقيّم احتياجات {name} في {service} وبعدها تجربة صغيرة محددة.",
        }
    if language == "ar":
        obs_line = f"لاحظنا في موقعكم: {obs}." if obs else ""
        return {
            "short_intro": f"السلام عليكم فريق {name}، نساعد الشركات المشابهة في {service}.",
            "email_subject": f"فكرة بخصوص {service} لـ {name}",
            "email_body": (
                f"السلام عليكم فريق {name}،\n\n{obs_line}\nنحن نساعد شركات مشابهة في {service} "
                "بطريقة تناسب طريقة عملكم الحالية. هل يناسبكم اتصال قصير لمدة 15 دقيقة لنتعرف على "
                'احتياجاتكم؟\n\nمع التحية\n\nإذا كنتم لا ترغبون في تلقي رسائل منا، يرجى الرد بكلمة "إلغاء".'
            ),
            "whatsapp_message": (
                f"مرحباً فريق {name} 👋 {obs_line} نقدم خدمة {service}. هل يناسبكم نتحدث باختصار؟ (للإلغاء أرسل: إلغاء)"
            ),
            "follow_up": f"أتابع رسالتي السابقة بخصوص {service}. هل الوقت مناسب للحديث هذا الأسبوع؟",
            "proposal_summary": f"مقترح مبدئي: تقييم احتياجات {name} في {service} ثم تنفيذ تجريبي محدود النطاق.",
        }
    obs_line = f"While reviewing your website I noticed {obs[0].lower() + obs[1:]}." if obs else ""
    return {
        "short_intro": f"Hi {name} team, we help businesses like yours with {service}.",
        "email_subject": f"An idea on {service} for {name}",
        "email_body": (
            f"Hi {name} team,\n\n{obs_line}\nWe help similar businesses with {service}, adapted to "
            "how they already work. Would a short 15-minute call be useful to see if it fits?\n\n"
            'Best regards\n\nIf you\'d prefer not to hear from us, just reply "unsubscribe".'
        ),
        "whatsapp_message": (
            f"Hi {name} team! {obs_line} We offer {service}. Open to a quick chat? (Reply STOP to opt out)"
        ),
        "follow_up": f"Following up on my note about {service} — would a quick call this week work?",
        "proposal_summary": f"Initial proposal: assess {name}'s needs around {service}, then a limited pilot.",
    }


def rule_based_spec(text: str) -> dict:
    """Keyword-based NL -> spec when no AI provider is configured."""
    from app.research.catalog import COUNTRIES

    low = text.lower()
    industry = next(
        (
            k
            for k, v in INDUSTRIES.items()
            if any(t in low for t in v["terms_en"]) or any(t in text for t in v["terms_ar"]) or v["en"].lower() in low
        ),
        None,
    )
    country = city = None
    for code, c in COUNTRIES.items():
        for en, ar in c["cities"]:
            if en.lower() in low or ar in text:
                country, city = code, en
                break
        if country:
            break
        if c["name_en"].lower() in low or c["name_ar"] in text:
            country = code
    services: list[str] = []  # offering ids are chosen in the wizard; keyword matching cannot know them
    return {
        "industry": industry or "medical_clinics",
        # False when no industry was recognised and the default above is only a placeholder (the bot asks instead).
        "industry_matched": industry is not None,
        "country": country,
        "city": city,
        "keywords": [],
        "excluded_keywords": [],
        "characteristics": [],
        "services": services[:3],
        "language": "ar" if any("؀" <= ch <= "ۿ" for ch in text) else "en",
        "parser": "rule_based",
    }
