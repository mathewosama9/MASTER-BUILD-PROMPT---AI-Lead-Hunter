"""DEMO MODE provider.

Produces clearly fictional businesses on the reserved `.example` TLD together with fixture HTML pages.
The fixture pages are served to the *real* website crawler and contact extractor through an in-memory
transport, so demo campaigns exercise the complete pipeline without any network access or paid keys.
All demo records are flagged `is_demo=True` and kept apart from real data.
"""

import hashlib
import random
import re

import httpx

from app.models.enums import ProviderStatus
from app.research.catalog import city_names, industry_label
from app.research.providers.base import (
    BusinessCandidate,
    ProviderContext,
    ProviderInfo,
    ProviderState,
    RateLimited,
    SearchQuery,
)

DEMO_TLD = "example"

_PREFIX_EN = [
    "Bright",
    "Al Noor",
    "Golden",
    "Prime",
    "Oasis",
    "Crescent",
    "Nova",
    "Summit",
    "Palm",
    "Horizon",
    "Lumen",
    "Cedar",
    "Falcon",
    "Pearl",
    "Atlas",
    "Sahara",
    "Zenith",
    "Mirage",
    "Harbor",
    "Nile",
]
_PREFIX_AR = [
    "المشرق",
    "النور",
    "الذهبي",
    "الريادة",
    "الواحة",
    "الهلال",
    "نوفا",
    "القمة",
    "النخيل",
    "الأفق",
    "لومن",
    "الأرز",
    "الصقر",
    "اللؤلؤة",
    "أطلس",
    "الصحراء",
    "الذروة",
    "السراب",
    "المرفأ",
    "النيل",
]
_SUFFIX = {
    "dental_clinics": ("Dental Care", "لطب الأسنان"),
    "medical_clinics": ("Medical Center", "المركز الطبي"),
    "real_estate": ("Properties", "للعقارات"),
    "ecommerce": ("Store", "متجر"),
    "restaurants": ("Kitchen", "مطبخ"),
    "education": ("Academy", "أكاديمية"),
    "beauty_salons": ("Beauty Lounge", "صالون"),
    "fitness": ("Fitness Club", "نادي"),
    "legal": ("Legal Partners", "للمحاماة"),
}

# Area codes that libphonenumber accepts as valid landlines; the subscriber part 555-01xx is fictional.
_PHONE_PREFIX = {"SA": "+966 11 555 0", "AE": "+971 4 555 0", "EG": "+20 2 2555 0"}


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def demo_profiles(query: SearchQuery, seed: str) -> list[dict]:
    rng = random.Random(int(hashlib.sha256(seed.encode()).hexdigest()[:12], 16))
    suffix_en, suffix_ar = _SUFFIX.get(query.industry, (industry_label(query.industry), ""))
    city_en, city_ar = city_names(query.country, query.city)
    slug_place = city_en or query.country
    count = max(1, min(query.limit + max(2, query.limit // 5), 120))
    profiles: list[dict] = []
    for i in range(count):
        p_en = _PREFIX_EN[i % len(_PREFIX_EN)]
        p_ar = _PREFIX_AR[i % len(_PREFIX_AR)]
        n = i // len(_PREFIX_EN)
        name_en = f"{p_en} {suffix_en}" + (f" {n + 1}" if n else "") + " (Demo)"
        name_ar = f"{p_ar} {suffix_ar}".strip()
        domain = f"{_slug(p_en)}-{_slug(suffix_en)}{n or ''}-{_slug(slug_place)}.{DEMO_TLD}"
        profiles.append(
            {
                "name": name_en,
                "name_ar": name_ar,
                "domain": domain,
                "city": city_en,
                "city_ar": city_ar,
                "has_booking": rng.random() < 0.4,
                "has_contact_form": rng.random() < 0.7,
                "has_whatsapp": rng.random() < 0.5,
                "has_live_chat": rng.random() < 0.2,
                "has_ecommerce": query.industry == "ecommerce" or rng.random() < 0.1,
                "has_email": rng.random() < 0.75,
                "has_phone": rng.random() < 0.85,
                "has_sales_email": rng.random() < 0.3,
                "no_contacts": rng.random() < 0.1,
                # Some businesses are already well automated -> fewer opportunities, lower scores.
                "has_crm": rng.random() < 0.25,
                "has_chatbot": rng.random() < 0.2,
                "bilingual": rng.random() < 0.6,
                "phone_suffix": f"{100 + i:03d}"[-3:],
                "description": f"{name_en.replace(' (Demo)', '')} is a fictional {suffix_en.lower()} in "
                f"{city_en or query.country} used for Rasd demo mode.",
            }
        )
    # A duplicate listing (same domain, different source URL) to exercise deduplication.
    if len(profiles) > 3:
        dup = dict(profiles[1])
        dup["duplicate_listing"] = True
        profiles.append(dup)
    return profiles


def render_demo_site(profile: dict, country: str, path: str) -> str | None:
    phone = f"{_PHONE_PREFIX.get(country, '+966 11 555 0')}{profile['phone_suffix']}"
    nav = '<nav><a href="/about">About</a> <a href="/services">Services</a> <a href="/contact">Contact</a>'
    if profile["has_booking"]:
        nav += ' <a href="/book">Book an appointment</a>'
    nav += "</nav>"
    contacts = ""
    if not profile["no_contacts"]:
        if profile["has_email"]:
            contacts += f'<p>Email: <a href="mailto:info@{profile["domain"]}">info@{profile["domain"]}</a></p>'
        if profile["has_sales_email"]:
            contacts += f'<p>Sales: <a href="mailto:sales@{profile["domain"]}">sales@{profile["domain"]}</a></p>'
        if profile["has_phone"]:
            contacts += f'<p>Call us: <a href="tel:{phone.replace(" ", "")}">{phone}</a></p>'
        if profile["has_whatsapp"]:
            digits = re.sub(r"\D", "", phone)
            contacts += f'<p><a href="https://wa.me/{digits}">WhatsApp us</a></p>'
    social = f'<a href="https://www.instagram.com/{_slug(profile["name"])}">Instagram</a>'
    chat = '<script src="https://embed.tawk.to/demo/widget.js"></script>' if profile["has_live_chat"] else ""
    if profile.get("has_chatbot"):
        chat += '<div class="chatbot" data-provider="botpress">Chatbot</div>'
    if profile.get("has_crm"):
        chat += '<div class="hsforms" data-portal="demo"></div>'
    shop = '<a href="/cart">Cart</a> <a href="/checkout">Checkout</a>' if profile["has_ecommerce"] else ""
    arabic = f'<p lang="ar">{profile["name_ar"]} — {profile.get("city_ar") or ""}</p>' if profile["bilingual"] else ""
    head = (
        f'<html lang="en"><head><title>{profile["name"]}</title>'
        f'<meta name="description" content="{profile["description"]}">'
        f'<meta name="viewport" content="width=device-width"></head><body>{nav}'
    )
    tail = f"<footer>{contacts}{social}</footer>{chat}</body></html>"
    if path in ("", "/"):
        return f"{head}<h1>{profile['name']}</h1><p>{profile['description']}</p>{arabic}{shop}{tail}"
    if path == "/about":
        return f"{head}<h1>About us</h1><p>{profile['description']} Serving {profile['city']}.</p>{tail}"
    if path == "/services":
        return f"{head}<h1>Our services</h1><ul><li>Consultations</li><li>Packages</li></ul>{tail}"
    if path == "/contact":
        form = (
            (
                '<form action="/contact" method="post"><input type="email" name="email">'
                '<textarea name="message"></textarea><button>Send</button></form>'
            )
            if profile["has_contact_form"]
            else ""
        )
        return f"{head}<h1>Contact</h1>{contacts}{form}{tail}"
    if path == "/book" and profile["has_booking"]:
        return f"{head}<h1>Book an appointment online</h1><p>Choose a time slot.</p>{tail}"
    if path == "/robots.txt":
        return "User-agent: *\nAllow: /\n"
    return None


class DemoSiteTransport(httpx.AsyncBaseTransport):
    """Serves fixture pages for `*.example` demo domains; everything else is refused."""

    def __init__(self, profiles: dict[str, dict], country: str) -> None:
        self.profiles = profiles
        self.country = country

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        host = request.url.host
        profile = self.profiles.get(host)
        if profile is None:
            return httpx.Response(404, text="not a demo host", request=request)
        body = render_demo_site(profile, self.country, request.url.path.rstrip("/") or "/")
        if body is None:
            return httpx.Response(404, text="not found", request=request)
        ctype = "text/plain" if request.url.path == "/robots.txt" else "text/html; charset=utf-8"
        return httpx.Response(200, text=body, headers={"content-type": ctype}, request=request)


class DemoProvider:
    info = ProviderInfo(
        key="demo",
        name="Demo fixtures",
        kind="discovery",
        description="Fictional businesses on the reserved .example domain. For testing the workflow only.",
        requires=[],
    )

    def state(self, ctx: ProviderContext) -> ProviderState:
        if not ctx.settings.get("demo_mode", True):
            return ProviderState(ProviderStatus.DISABLED, "Demo mode is disabled (DEMO_MODE=false).")
        return ProviderState(ProviderStatus.CONNECTED, "Demo mode: fictional data only.")

    async def search_businesses(self, query: SearchQuery, ctx: ProviderContext) -> list[BusinessCandidate]:
        if ctx.settings.get("simulate_rate_limit"):
            await ctx.record_usage(self.info.key, "search", 1, 0.0, False, 429)
            raise RateLimited("Simulated demo rate limit", retry_after=0.01)
        seed = f"{ctx.campaign_id}:{query.country}:{query.city}:{query.industry}"
        out: list[BusinessCandidate] = []
        for idx, p in enumerate(demo_profiles(query, seed)):
            await ctx.record_usage(self.info.key, "search", 1, 0.0, True, 200)
            out.append(
                BusinessCandidate(
                    name=p["name"],
                    website_url=f"https://{p['domain']}",
                    industry=query.industry,
                    country=query.country,
                    city=p["city"],
                    description=p["description"],
                    source_provider=self.info.key,
                    source_url=f"https://directory.example/listing/{idx}",
                    source_title=p["name"],
                    raw={"demo_profile": p},
                    is_demo=True,
                )
            )
        return out

    async def test_connection(self, ctx: ProviderContext) -> ProviderState:
        return self.state(ctx)
