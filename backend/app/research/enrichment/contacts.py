"""Extract clearly published business contact channels from HTML.

Only visible, published channels are collected (mailto/tel/wa.me links and plain-text emails/phones).
Nothing is guessed: emails are never synthesised from name patterns, and a published email is labelled
`discovered`, never `verified`, until a verification provider confirms deliverability.
"""

import json
import re
from dataclasses import dataclass, field
from urllib.parse import unquote, urljoin, urlparse

import phonenumbers
from selectolax.lexbor import LexborHTMLParser as HTMLParser

from app.models.enums import ContactType, VerificationStatus
from app.research.enrichment.normalize import normalize_domain, normalize_email, normalize_phone

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,24}")
PHONE_RE = re.compile(r"(?:\+|00)\d[\d\s\-().]{7,18}\d")


def find_phones(text: str, country: str | None) -> list[str]:
    """Phone numbers written in text: international ones (+/00) always, and - when the market is known - local
    ones with the trunk prefix ("050 123 4567", "02 123 4567"), kept only when valid for that country. Bare digit
    runs without a leading 0 (order numbers, registration ids) are never read as phones."""
    found = list(dict.fromkeys(PHONE_RE.findall(text or "")))
    if country and text:
        try:
            matcher = phonenumbers.PhoneNumberMatcher(text, country.upper(), leniency=phonenumbers.Leniency.VALID)
            for m in matcher:
                raw = m.raw_string.strip()
                if raw.startswith("0") and not raw.startswith("00") and raw not in found:
                    found.append(raw)
        except Exception:  # noqa: BLE001, S110 - an unknown region code just means no local numbers
            pass
    return found


ROLE_PREFIXES = {
    "info": "general",
    "contact": "general",
    "hello": "general",
    "office": "general",
    "admin": "general",
    "enquiries": "general",
    "inquiries": "general",
    "reception": "general",
    "sales": "sales",
    "marketing": "sales",
    "business": "sales",
    "partnerships": "sales",
    "support": "support",
    "help": "support",
    "care": "support",
    "customerservice": "support",
    "booking": "booking",
    "appointments": "booking",
    "reservations": "booking",
    "hr": "hr",
    "careers": "hr",
    "jobs": "hr",
}
FREE_MAIL = {"gmail.com", "hotmail.com", "outlook.com", "yahoo.com", "icloud.com", "live.com"}
IGNORED_EMAIL_DOMAINS = {
    "example.com",
    "example.org",
    "example.net",
    "sentry.io",
    "wixpress.com",
    "domain.com",
    "email.com",
    "yourdomain.com",
    "yoursite.com",
    "mysite.com",
    "company.com",
    "test.com",
    # disposable mailboxes
    "mailinator.com",
    "guerrillamail.com",
    "10minutemail.com",
    "tempmail.com",
    "temp-mail.org",
    "yopmail.com",
    "trashmail.com",
    "sharklasers.com",
}
# Template and placeholder mailboxes left in themes ("your@email.com", "name@company.com").
PLACEHOLDER_LOCALS = {
    "your",
    "youremail",
    "yourname",
    "name",
    "user",
    "username",
    "email",
    "test",
    "example",
    "someone",
    "johndoe",
    "john.doe",
    "janedoe",
    "jane.doe",
    "firstname.lastname",
    "first.last",
}


def is_junk_email(email: str) -> bool:
    """Not a real mailbox of the business: placeholders, image file names, error-tracker ids, disposable domains."""
    local, _, domain = (email or "").lower().rpartition("@")
    if not local or not domain:
        return True
    if domain in IGNORED_EMAIL_DOMAINS or any(domain.endswith("." + d) for d in IGNORED_EMAIL_DOMAINS):
        return True
    if local in PLACEHOLDER_LOCALS or re.fullmatch(r"[0-9a-f]{24,}", local):
        return True
    return bool(re.search(r"\.(png|jpe?g|gif|webp|svg|avif)$", email) or re.search(r"@\d+x\.", email))


SOCIAL_HOSTS = {
    "facebook.com": "facebook",
    "instagram.com": "instagram",
    "linkedin.com": "linkedin",
    "x.com": "x",
    "twitter.com": "x",
    "tiktok.com": "tiktok",
    "youtube.com": "youtube",
    "snapchat.com": "snapchat",
}
CONTACT_PATH_HINTS = ("contact", "اتصل", "تواصل", "contact-us")


@dataclass
class ContactFinding:
    type: ContactType
    value: str
    normalized_value: str
    source_url: str
    subtype: str | None = None
    confidence: float = 0.6
    verification_status: VerificationStatus = VerificationStatus.DISCOVERED
    usage_restrictions: str | None = None
    person_name: str | None = None
    person_role: str | None = None
    source_provider: str = "website"


@dataclass
class ExtractionResult:
    contacts: list[ContactFinding] = field(default_factory=list)

    def add(self, finding: ContactFinding) -> None:
        for existing in self.contacts:
            if existing.type == finding.type and existing.normalized_value == finding.normalized_value:
                existing.confidence = max(existing.confidence, finding.confidence)
                return
        self.contacts.append(finding)


def classify_email(email: str, site_domain: str | None) -> tuple[str | None, float, str | None]:
    """Return (subtype, confidence, usage_restriction)."""
    local, _, domain = email.partition("@")
    key = re.sub(r"[^a-z]", "", local.lower())
    subtype = ROLE_PREFIXES.get(key)
    on_domain = site_domain is not None and normalize_domain(domain) == site_domain
    if domain in FREE_MAIL:
        return subtype or "general", 0.45, "Free-mail address published on the business website."
    if subtype:
        return subtype, 0.8 if on_domain else 0.6, None
    # A non-role mailbox (likely a named individual). Keep, but flag as personal data.
    return (
        "individual",
        0.5 if on_domain else 0.35,
        ("Appears to be an individual's mailbox. Treat as personal data; confirm lawful basis before use."),
    )


# Path prefixes that are posts, shares or app pages, not a business profile.
_SOCIAL_NON_PROFILE = (
    "sharer",
    "share",
    "intent",
    "p/",
    "reel",
    "reels",
    "stories",
    "explore",
    "watch",
    "hashtag",
    "search",
    "login",
    "signup",
    "accounts",
    "dialog",
    "plugins",
    "tr",
    "events",
    "groups",
    "photo",
    "video",
    "status",
    "home",
    "privacy",
    "legal",
    "about/privacy",
    "help",
)


def social_profile_url(url: str) -> tuple[str | None, str]:
    """Return (platform, canonical profile URL) for a business profile link, or (None, url) otherwise."""
    parsed = urlparse(url if "://" in url else f"https://{url}")
    host = (parsed.hostname or "").lower().removeprefix("www.").removeprefix("m.").removeprefix("web.")
    platform = SOCIAL_HOSTS.get(host)
    path = parsed.path.strip("/")
    if not platform or not path:
        return None, url
    low = path.lower() + "/"
    if any(low.startswith(p if p.endswith("/") else p + "/") for p in _SOCIAL_NON_PROFILE):
        return None, url
    if platform == "linkedin" and not low.startswith(("company/", "school/", "showcase/")):
        return None, url  # personal LinkedIn profiles are out of scope
    if platform == "facebook" and low.startswith("profile.php"):
        return None, url  # numeric personal profiles
    if platform in ("instagram", "x", "tiktok"):
        path = path.split("/")[0]  # drop /p/..., /status/... tails
    if platform == "snapchat" and not low.startswith(("add/", "@")):
        return None, url
    return platform, f"https://www.{host}/{path}".rstrip("/")


# schema.org types that describe a person, a page or media rather than the business itself.
_NON_BUSINESS_TYPES = {
    "person",
    "website",
    "webpage",
    "breadcrumblist",
    "imageobject",
    "videoobject",
    "searchaction",
    "sitenavigationelement",
    "article",
    "blogposting",
    "faqpage",
    "question",
    "answer",
    "review",
    "offer",
}


def parse_json_ld(html: str) -> list[dict]:
    """Business entities (Organization/LocalBusiness/...) published as JSON-LD structured data."""
    tree = HTMLParser(html)
    out: list[dict] = []

    def visit(node: object) -> None:
        if isinstance(node, list):
            for n in node:
                visit(n)
            return
        if not isinstance(node, dict):
            return
        if "@graph" in node:
            visit(node["@graph"])
        types = node.get("@type")
        types = [types] if isinstance(types, str) else [t for t in (types or []) if isinstance(t, str)]
        if types and not any(t.lower() in _NON_BUSINESS_TYPES for t in types):
            if any(k in node for k in ("telephone", "email", "sameAs", "address", "openingHours", "url")):
                out.append(node)

    for script in tree.css('script[type="application/ld+json"]'):
        text = (script.text() or "").strip()
        if not text:
            continue
        try:
            visit(json.loads(text))
        except ValueError:
            continue  # malformed JSON-LD is common; ignore rather than guess
    return out


def _as_list(v: object) -> list:
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def _structured_contacts(
    result: ExtractionResult, entities: list[dict], page_url: str, country: str | None, site_domain: str | None
) -> None:
    for e in entities:
        for phone in _as_list(e.get("telephone")):
            if isinstance(phone, str):
                _add_phone(result, phone, page_url, country, bonus=0.15)
        for email in _as_list(e.get("email")):
            if isinstance(email, str):
                _add_email(result, email.removeprefix("mailto:"), page_url, site_domain, bonus=0.1)
        for link in _as_list(e.get("sameAs")):
            if isinstance(link, str):
                platform, canon = social_profile_url(link)
                if platform:
                    result.add(
                        ContactFinding(
                            ContactType.SOCIAL, canon, canon.lower(), page_url, subtype=platform, confidence=0.85
                        )
                    )


def extract_contacts(html: str, page_url: str, country: str | None, site_domain: str | None) -> ExtractionResult:
    result = ExtractionResult()
    _structured_contacts(result, parse_json_ld(html), page_url, country, site_domain)
    tree = HTMLParser(html)
    for node in tree.css("script, style, noscript, template"):
        node.decompose()

    for a in tree.css("a[href]"):
        href = (a.attributes.get("href") or "").strip()
        low = href.lower()
        if low.startswith("mailto:"):
            _add_email(result, unquote(href[7:].split("?")[0]), page_url, site_domain, bonus=0.05)
        elif low.startswith("tel:"):
            _add_phone(result, unquote(href[4:]), page_url, country, bonus=0.05)
        elif "wa.me/" in low or "api.whatsapp.com/send" in low:
            digits = (
                re.sub(r"\D", "", low.split("wa.me/")[-1].split("?")[0])
                if "wa.me/" in low
                else re.sub(r"\D", "", (re.search(r"phone=(\d+)", low) or [""])[0])
            )
            e164 = normalize_phone("+" + digits, None) if digits else None
            if e164:
                result.add(
                    ContactFinding(ContactType.WHATSAPP, e164, e164, page_url, subtype="business", confidence=0.8)
                )
        else:
            abs_url = urljoin(page_url, href)
            platform, canon = social_profile_url(abs_url)
            if platform:
                result.add(
                    ContactFinding(ContactType.SOCIAL, canon, canon.lower(), page_url, subtype=platform, confidence=0.7)
                )
            elif (
                site_domain
                and normalize_domain(abs_url) == site_domain
                and any(h in unquote(abs_url).lower() for h in CONTACT_PATH_HINTS)
            ):
                canon = abs_url.split("#")[0].rstrip("/")
                result.add(ContactFinding(ContactType.CONTACT_PAGE, canon, canon.lower(), page_url, confidence=0.9))

    body = tree.body.text(separator=" ") if tree.body else ""
    for email in set(EMAIL_RE.findall(body)):
        _add_email(result, email, page_url, site_domain)
    for phone in find_phones(body, country):
        _add_phone(result, phone, page_url, country)
    return result


def _add_email(result: ExtractionResult, raw: str, page_url: str, site_domain: str | None, bonus: float = 0.0) -> None:
    email = normalize_email(raw)
    if not email:
        return
    if is_junk_email(email):
        return
    subtype, conf, restriction = classify_email(email, site_domain)
    result.add(
        ContactFinding(
            ContactType.EMAIL,
            email,
            email,
            page_url,
            subtype=subtype,
            confidence=min(conf + bonus, 0.95),
            usage_restrictions=restriction,
        )
    )


def _add_phone(result: ExtractionResult, raw: str, page_url: str, country: str | None, bonus: float = 0.0) -> None:
    e164 = normalize_phone(raw, country)
    if e164:
        result.add(
            ContactFinding(
                ContactType.PHONE, raw.strip(), e164, page_url, subtype="business", confidence=min(0.7 + bonus, 0.95)
            )
        )
