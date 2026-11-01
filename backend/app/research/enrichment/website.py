"""Website research adapter: bounded, robots-aware crawl of a company's public pages.

Collects page excerpts and *observed* signals (booking, contact form, live chat, WhatsApp, e-commerce...).
A signal that is not seen is recorded as `observed=False` ("not observed on inspected pages"), never as
"the business lacks this feature".
"""

import logging
import re
from dataclasses import dataclass, field
from urllib.parse import unquote, urljoin, urlparse

import httpx
from selectolax.lexbor import LexborHTMLParser as HTMLParser

from app.core.safe_http import RobotsDisallowed, SafeFetcher, UnsafeURLError
from app.research.enrichment.contacts import ExtractionResult, extract_contacts, parse_json_ld
from app.research.enrichment.decision_makers import (
    DecisionMaker,
    contacts_near,
    from_cards,
    from_json_ld,
    from_text,
)
from app.research.enrichment.normalize import normalize_domain

log = logging.getLogger(__name__)

PAGE_PATTERNS: dict[str, tuple[str, ...]] = {
    # Checked before "about": team/leadership pages name the people who run the business.
    "team": (
        "team",
        "leadership",
        "management",
        "our-doctors",
        "doctors",
        "physicians",
        "founder",
        "staff",
        "board",
        "directors",
        "principal",
        "our-people",
        "faculty",
        "partners",
        "message-from",
        "chairman",
        "مجلس-الإدارة",
        "مجلس الإدارة",
        "كلمة-المدير",
        "كلمة المدير",
        "كلمة-المؤسس",
        "كلمة الرئيس",
        "الهيئة",
        "فريق",
        "الأطباء",
        "أطباؤنا",
        "اطباؤنا",
        "الإدارة",
        "الادارة",
        "المؤسس",
    ),
    "about": ("about", "who-we-are", "من-نحن", "من نحن", "عن"),
    "services": ("service", "treatment", "solutions", "products", "خدمات", "خدماتنا"),
    "contact": ("contact", "اتصل", "تواصل"),
    "booking": ("book", "appointment", "reserve", "حجز", "موعد"),
    "faq": ("faq", "questions", "الأسئلة"),
}

SIGNALS: dict[str, dict] = {
    "online_booking": {
        "label": "Online booking / appointment page",
        "text": r"book (an )?appointment|book online|reserve now|احجز|حجز موعد|book now",
        "html": r"calendly\.com|setmore|simplybook|acuityscheduling|vezeeta|zocdoc|booksy|fresha",
    },
    "contact_form": {"label": "Website contact form", "custom": "form"},
    "live_chat": {
        "label": "Live chat widget",
        "html": r"tawk\.to|intercom|crisp\.chat|zendesk|livechatinc|tidio|drift\.com|freshchat|hubspot.*conversations",
    },
    "chatbot": {"label": "Chatbot", "html": r"chatbot|botpress|dialogflow|manychat|landbot"},
    "whatsapp_link": {"label": "WhatsApp click-to-chat link", "html": r"wa\.me/|api\.whatsapp\.com"},
    "ecommerce": {
        "label": "Online store / checkout",
        "html": r"/cart|/checkout|add to cart|shopify|woocommerce|salla\.sa|zid\.sa|سلة الشراء|أضف للسلة",
    },
    "online_payment": {
        "label": "Online payment",
        "html": r"stripe\.com|checkout\.com|tap\.company|paytabs|hyperpay|mada",
    },
    "crm_forms": {"label": "Marketing/CRM form embed", "html": r"hsforms|hubspot|zoho|salesforce|pipedrive|marketo"},
    "arabic_content": {"label": "Arabic content", "custom": "arabic"},
    "english_content": {"label": "English content", "custom": "english"},
    "faq_page": {"label": "FAQ page", "custom": "faq"},
    "mobile_viewport": {"label": "Mobile-friendly viewport meta", "html": r'name="viewport"'},
    "https": {"label": "Served over HTTPS", "custom": "https"},
}


@dataclass
class PageSnapshot:
    url: str
    kind: str
    title: str | None
    excerpt: str


@dataclass
class SignalObservation:
    key: str
    label: str
    observed: bool
    url: str | None = None
    excerpt: str | None = None


@dataclass
class WebsiteResearch:
    url: str
    reachable: bool
    error: str | None = None
    title: str | None = None
    description: str | None = None
    pages: list[PageSnapshot] = field(default_factory=list)
    signals: list[SignalObservation] = field(default_factory=list)
    contacts: ExtractionResult = field(default_factory=ExtractionResult)
    # From schema.org JSON-LD published by the site itself.
    structured_name: str | None = None
    address: str | None = None
    opening_hours: str | None = None
    # Decision makers named on the site (schema.org data and clear "role: name" text); see decision_makers.
    people: list[DecisionMaker] = field(default_factory=list)


# How many pages of each kind to read; several team/management pages are common (board, doctors, management).
KIND_LIMITS = {"team": 3, "about": 2}


def _classify_link(href: str, text: str) -> str | None:
    hay = (unquote(href) + " " + text).lower()
    for kind, needles in PAGE_PATTERNS.items():
        if any(n in hay for n in needles):
            return kind
    return None


def _visible_text(tree: HTMLParser, limit: int = 2500) -> str:
    for node in tree.css("script, style, noscript, svg, template"):
        node.decompose()
    text = tree.body.text(separator=" ") if tree.body else ""
    return re.sub(r"\s+", " ", text).strip()[:limit]


async def research_website(
    url: str,
    *,
    country: str | None,
    max_pages: int = 8,
    transport: httpx.AsyncBaseTransport | None = None,
    skip_dns_check: bool = False,
    roles: tuple[str, ...] = (),
) -> WebsiteResearch:
    domain = normalize_domain(url)
    result = WebsiteResearch(url=url, reachable=False)
    raw_html: dict[str, str] = {}
    async with SafeFetcher(transport=transport, skip_dns_check=skip_dns_check) as fetcher:
        try:
            home = await fetcher.get(url)
        except RobotsDisallowed:
            result.error = "robots.txt disallows crawling"
            return result
        except (UnsafeURLError, httpx.HTTPError) as exc:
            result.error = f"{type(exc).__name__}: {exc}"[:300]
            return result
        if home.status_code >= 400 or "html" not in home.content_type:
            result.error = f"Homepage returned {home.status_code} ({home.content_type or 'unknown type'})"
            return result
        result.reachable = True
        raw_html[home.url] = home.text
        tree = HTMLParser(home.text)
        result.title = tree.css_first("title").text(strip=True) if tree.css_first("title") else None
        meta = tree.css_first('meta[name="description"]')
        result.description = (meta.attributes.get("content") or "").strip() or None if meta else None

        to_visit: dict[str, str] = {}
        for a in tree.css("a[href]"):
            href = a.attributes.get("href") or ""
            absolute = urljoin(home.url, href).split("#")[0]
            if normalize_domain(absolute) != domain or absolute.rstrip("/") == home.url.rstrip("/"):
                continue
            kind = _classify_link(urlparse(absolute).path, a.text(strip=True))
            if kind and absolute not in to_visit and _room(to_visit, kind):
                to_visit[absolute] = kind
        result.pages.append(PageSnapshot(home.url, "home", result.title, _visible_text(HTMLParser(home.text))))
        _apply_structured(result, home.text)

        if not {"about", "contact"} <= set(to_visit.values()):
            # JS-built menus hide links from plain HTML; the sitemap usually still lists the pages.
            for page_url, kind in (await _sitemap_pages(fetcher, home.url, domain)).items():
                if page_url not in to_visit and _room(to_visit, kind):
                    to_visit[page_url] = kind

        # Pages that name the people and contacts are read first when the page budget is small.
        order = {"about": 0, "team": 1, "contact": 2, "booking": 3, "services": 4, "faq": 5}
        ranked = sorted(to_visit.items(), key=lambda kv: order.get(kv[1], 9))
        for page_url, kind in ranked[: max(0, max_pages - 1)]:
            try:
                page = await fetcher.get(page_url)
            except (RobotsDisallowed, UnsafeURLError, httpx.HTTPError) as exc:
                log.info("page skipped", extra={"url": page_url, "reason": str(exc)[:120]})
                continue
            if page.status_code >= 400 or "html" not in page.content_type:
                continue
            raw_html[page.url] = page.text
            ptree = HTMLParser(page.text)
            title = ptree.css_first("title").text(strip=True) if ptree.css_first("title") else None
            limit = 4000 if kind in ("about", "team") else 2500
            result.pages.append(PageSnapshot(page.url, kind, title, _visible_text(ptree, limit)))

    for page_url, html in raw_html.items():
        for c in extract_contacts(html, page_url, country, domain).contacts:
            result.contacts.add(c)
    result.signals = _detect_signals(raw_html, result)
    kinds = {p.url: p.kind for p in result.pages}
    for page_url, html in raw_html.items():
        result.people.extend(from_json_ld(html, page_url))
        if kinds.get(page_url) in ("home", "about", "team", "contact"):
            result.people.extend(from_cards(html, page_url, roles))
    for page in result.pages:
        if page.kind in ("home", "about", "team", "contact"):
            result.people.extend(from_text(page.excerpt, page.url, "website", extra_roles=roles))
    # A person's own email/phone/WhatsApp/profiles printed next to their name. Values printed on several pages
    # (header/footer lines) are the business's, not the person's.
    shared = _sitewide_values(raw_html, country, domain)
    for page_url, html in raw_html.items():
        contacts_near(html, result.people, page_url, country, shared=shared)
    return result


def _room(to_visit: dict[str, str], kind: str) -> bool:
    return sum(1 for k in to_visit.values() if k == kind) < KIND_LIMITS.get(kind, 1)


def _sitewide_values(raw_html: dict[str, str], country: str | None, domain: str | None) -> set[str]:
    seen: dict[str, int] = {}
    for page_url, html in raw_html.items():
        for c in extract_contacts(html, page_url, country, domain).contacts:
            seen[c.normalized_value] = seen.get(c.normalized_value, 0) + 1
    if len(raw_html) == 1:
        return set()
    return {v for v, n in seen.items() if n >= 2}


def _apply_structured(result: WebsiteResearch, html: str) -> None:
    for entity in parse_json_ld(html):
        name = entity.get("name")
        if isinstance(name, str) and not result.structured_name:
            result.structured_name = name.strip()[:300] or None
        desc = entity.get("description")
        if isinstance(desc, str) and not result.description:
            result.description = desc.strip()[:2000] or None
        addr = entity.get("address")
        if isinstance(addr, dict) and not result.address:
            parts = [addr.get(k) for k in ("streetAddress", "addressLocality", "addressRegion", "postalCode")]
            result.address = ", ".join(p.strip() for p in parts if isinstance(p, str) and p.strip())[:500] or None
        elif isinstance(addr, str) and not result.address:
            result.address = addr.strip()[:500] or None
        hours = entity.get("openingHours")
        if hours and not result.opening_hours:
            result.opening_hours = (", ".join(hours) if isinstance(hours, list) else str(hours))[:300]


SITEMAP_LOC_RE = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.I)


async def _sitemap_pages(fetcher: SafeFetcher, home_url: str, domain: str | None) -> dict[str, str]:
    """Classify same-site page URLs listed in /sitemap.xml (one nested sitemap level at most)."""
    found: dict[str, str] = {}
    queue = [urljoin(home_url, "/sitemap.xml")]
    for depth in range(2):
        next_queue: list[str] = []
        for sm_url in queue[:3]:
            try:
                resp = await fetcher.get(sm_url, limit=400_000)
            except (RobotsDisallowed, UnsafeURLError, httpx.HTTPError):
                continue
            if resp.status_code >= 400 or ("xml" not in resp.content_type and "<urlset" not in resp.text):
                continue
            for loc in SITEMAP_LOC_RE.findall(resp.text)[:2000]:
                if normalize_domain(loc) != domain:
                    continue
                if loc.lower().endswith(".xml"):
                    if depth == 0:
                        next_queue.append(loc)
                    continue
                kind = _classify_link(urlparse(loc).path, "")
                if kind and loc not in found and _room(found, kind):
                    found[loc] = kind
        queue = next_queue
        if not queue:
            break
    return found


def _detect_signals(raw_html: dict[str, str], research: WebsiteResearch) -> list[SignalObservation]:
    out: list[SignalObservation] = []
    kinds = {p.kind for p in research.pages}
    for key, spec in SIGNALS.items():
        hit_url, excerpt = None, None
        custom = spec.get("custom")
        if custom == "form":
            for u, html in raw_html.items():
                tree = HTMLParser(html)
                for form in tree.css("form"):
                    if form.css_first("textarea") or form.css_first('input[type="email"]'):
                        hit_url, excerpt = u, "Form with message/email fields"
                        break
                if hit_url:
                    break
        elif custom == "arabic":
            for p in research.pages:
                if re.search(r"[؀-ۿ]{3,}", p.excerpt):
                    hit_url, excerpt = p.url, re.search(r"[؀-ۿ][؀-ۿ\s]{2,60}", p.excerpt).group(0)
                    break
        elif custom == "english":
            for p in research.pages:
                if re.search(r"\b(the|and|our|we|with)\b", p.excerpt, re.I):
                    hit_url, excerpt = p.url, p.excerpt[:80]
                    break
        elif custom == "faq":
            if "faq" in kinds:
                page = next(p for p in research.pages if p.kind == "faq")
                hit_url, excerpt = page.url, page.title
        elif custom == "https":
            if research.pages and research.pages[0].url.startswith("https://"):
                hit_url, excerpt = research.pages[0].url, "HTTPS homepage"
        else:
            patterns = [(spec.get("text"), True), (spec.get("html"), False)]
            for u, html in raw_html.items():
                for pattern, text_only in patterns:
                    if not pattern:
                        continue
                    hay = _visible_text(HTMLParser(html), 20000) if text_only else html
                    m = re.search(pattern, hay, re.I)
                    if m:
                        start = max(0, m.start() - 40)
                        hit_url, excerpt = u, re.sub(r"\s+", " ", hay[start : m.end() + 40]).strip()[:160]
                        break
                if hit_url:
                    break
            if key == "online_booking" and not hit_url and "booking" in kinds:
                page = next(p for p in research.pages if p.kind == "booking")
                hit_url, excerpt = page.url, page.title
        out.append(SignalObservation(key, spec["label"], hit_url is not None, hit_url, excerpt))
    return out
