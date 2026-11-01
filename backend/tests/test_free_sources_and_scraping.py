# ruff: noqa: E501  (fixture HTML mirrors real single-line meta tags)
"""OpenStreetMap, file import, JSON-LD/sitemap, DNS MX check, Google Maps and social-profile scraping.

Network and browser are faked: OSM via httpx.MockTransport, websites via a site transport, and the headless
browser via a `PageSource` stub serving synthetic pages shaped like the real ones.
"""

import base64
import json
import uuid

import httpx
import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.models import Business, BusinessContact, BusinessEvidence, CampaignRun
from app.models.enums import ProviderStatus, VerificationStatus
from app.research.enrichment.contacts import extract_contacts, parse_json_ld, social_profile_url
from app.research.enrichment.dedupe import dedupe_candidates, identity_key
from app.research.providers.base import BusinessCandidate, ProviderContext, ProviderError, SearchQuery
from app.research.providers.google_maps import GoogleMapsProvider
from app.research.providers.osm import OsmProvider
from app.research.providers.registry import get_discovery_provider
from app.research.scraping.parsers import (
    ScrapeBlocked,
    is_blocked,
    maps_feature_id,
    parse_count,
    parse_maps_place,
    parse_social_profile,
)
from app.services.imports import ImportError_, parse_import

Q = SearchQuery(country="SA", city="Riyadh", industry="dental_clinics", limit=10)

# ----------------------------------------------------------------------------- fixtures: OSM

OVERPASS = {
    "elements": [
        {"type": "node", "id": 1, "tags": {"name": "No Contact Dental", "amenity": "dentist"}},
        {
            "type": "node",
            "id": 2,
            "lat": 24.7,
            "lon": 46.6,
            "tags": {
                "name": "Smile Dental",
                "name:ar": "عيادة الابتسامة",
                "amenity": "dentist",
                "website": "smile-dental.sa",
                "phone": "+966 11 234 5678;+966 11 000 0000",
                "contact:instagram": "smiledental",
                "opening_hours": "Sa-Th 09:00-21:00",
            },
        },
        {
            "type": "way",
            "id": 3,
            "center": {"lat": 24.71, "lon": 46.61},
            "tags": {"name": "Phone Only Clinic", "amenity": "dentist", "contact:phone": "0112223333"},
        },
        {"type": "node", "id": 2, "tags": {"name": "Smile Dental", "amenity": "dentist"}},  # duplicate element
    ]
}


def osm_transport(calls: list[str] | None = None) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(str(request.url))
        if "nominatim" in request.url.host:
            assert request.headers["user-agent"].startswith("AILeadHunter")
            return httpx.Response(200, json=[{"osm_type": "relation", "osm_id": 123}])
        body = request.content.decode()
        assert "area(id:3600000123)" in httpx.QueryParams(body)["data"]
        return httpx.Response(200, json=OVERPASS)

    return httpx.MockTransport(handler)


def ctx() -> ProviderContext:
    return ProviderContext(credentials={}, settings={})


async def test_osm_returns_real_listing_fields_ranked_by_contactability():
    calls: list[str] = []
    found = await OsmProvider(osm_transport(calls), pause=0).search_businesses(Q, ctx())
    assert [c.name for c in found] == ["Smile Dental", "Phone Only Clinic", "No Contact Dental"]
    smile = found[0]
    assert smile.website_url == "https://smile-dental.sa"
    assert smile.phone == "+966 11 234 5678"  # first of a ;-list
    assert smile.identifiers == {"osm": "node/2"}
    assert smile.social_urls == ["https://www.instagram.com/smiledental"]
    assert smile.source_url == "https://www.openstreetmap.org/node/2"
    assert smile.raw["opening_hours"] == "Sa-Th 09:00-21:00" and "OpenStreetMap" in smile.raw["attribution"]
    assert found[1].raw["lat"] == 24.71  # ways use their computed center
    assert len(calls) == 2


async def test_osm_unsupported_industry_is_explicit():
    with pytest.raises(ProviderError, match="no map category"):
        await OsmProvider(osm_transport(), pause=0).search_businesses(
            Q.model_copy(update={"industry": "ecommerce"}), ctx()
        )


async def test_osm_rate_limit_is_retryable():
    transport = httpx.MockTransport(lambda r: httpx.Response(429, headers={"retry-after": "3"}))
    from app.research.providers.base import RateLimited

    with pytest.raises(RateLimited):
        await OsmProvider(transport, pause=0).search_businesses(Q, ctx())


def test_listing_ids_dedupe_when_no_domain_or_phone():
    a = BusinessCandidate(name="A", source_provider="osm", source_url="u1", identifiers={"osm": "node/9"})
    b = BusinessCandidate(name="A again", source_provider="osm", source_url="u2", identifiers={"osm": "node/9"})
    c = BusinessCandidate(
        name="Other", source_provider="google_maps", source_url="u3", identifiers={"gmaps": "0x1:0x2"}
    )
    assert identity_key(a) == "osm:node/9" and identity_key(c) == "gmaps:0x1:0x2"
    groups, removed = dedupe_candidates([a, b, c])
    assert removed == 1 and len(groups) == 2


# ----------------------------------------------------------------------------- website quality

JSON_LD_PAGE = """<html><head>
<script type="application/ld+json">{"@context":"https://schema.org","@graph":[
 {"@type":"WebSite","url":"https://smile-dental.sa"},
 {"@type":["Dentist","LocalBusiness"],"name":"Smile Dental Clinic","telephone":"+966112345678",
  "email":"info@smile-dental.sa","openingHours":["Sa-Th 09:00-21:00"],
  "address":{"streetAddress":"King Fahd Rd","addressLocality":"Riyadh"},
  "sameAs":["https://www.instagram.com/smiledental/","https://www.snapchat.com/add/smiledental",
            "https://www.instagram.com/p/POSTID/","https://www.linkedin.com/in/some-person"]},
 {"@type":"Person","name":"Dr Someone","telephone":"+966500000000"}
]}</script>
<script type="application/ld+json">{ not json </script>
</head><body>Welcome</body></html>"""


def test_json_ld_contacts_are_extracted_with_higher_confidence():
    res = extract_contacts(JSON_LD_PAGE, "https://smile-dental.sa/", "SA", "smile-dental.sa")
    by = {(c.type, c.normalized_value): c for c in res.contacts}
    assert by[("phone", "+966112345678")].confidence >= 0.85
    assert ("email", "info@smile-dental.sa") in by
    socials = sorted(c.value for c in res.contacts if c.type == "social")
    assert socials == ["https://www.instagram.com/smiledental", "https://www.snapchat.com/add/smiledental"]
    assert ("phone", "+966500000000") not in by  # Person entities are not business data
    entities = parse_json_ld(JSON_LD_PAGE)
    assert [e["name"] for e in entities] == ["Smile Dental Clinic"]


@pytest.mark.parametrize(
    ("url", "platform"),
    [
        ("https://instagram.com/acme/", "instagram"),
        ("https://www.instagram.com/p/abc", None),
        ("https://m.facebook.com/AcmeClinic", "facebook"),
        ("https://www.facebook.com/sharer/sharer.php?u=x", None),
        ("https://www.facebook.com/profile.php?id=1", None),
        ("https://www.linkedin.com/company/acme", "linkedin"),
        ("https://www.linkedin.com/in/jane", None),
        ("https://www.snapchat.com/add/acme", "snapchat"),
        ("https://www.tiktok.com/@acme/video/1", "tiktok"),
        ("https://example.com/acme", None),
    ],
)
def test_social_profile_url_keeps_business_profiles_only(url, platform):
    assert social_profile_url(url)[0] == platform


async def test_sitemap_finds_pages_hidden_from_html_menu(monkeypatch):
    from app.core import safe_http
    from app.research.enrichment.website import research_website

    async def no_dns(self, url):
        return url

    monkeypatch.setattr(safe_http.SafeFetcher, "_check", no_dns)
    pages = {
        "/": JSON_LD_PAGE,
        "/sitemap.xml": "<urlset><url><loc>https://smile-dental.sa/sitemap-pages.xml</loc></url></urlset>",
        "/sitemap-pages.xml": (
            "<urlset><url><loc>https://smile-dental.sa/en/contact-us</loc></url>"
            "<url><loc>https://other.sa/about</loc></url></urlset>"
        ),
        "/en/contact-us": '<html><body><a href="mailto:bookings@smile-dental.sa">mail</a></body></html>',
    }

    def handler(request):
        body = pages.get(request.url.path)
        if body is None:
            return httpx.Response(404, text="nope")
        ctype = "application/xml" if request.url.path.endswith(".xml") else "text/html"
        return httpx.Response(200, text=body, headers={"content-type": ctype})

    res = await research_website(
        "https://smile-dental.sa/", country="SA", transport=httpx.MockTransport(handler), skip_dns_check=True
    )
    assert any(p.url.endswith("/en/contact-us") for p in res.pages)
    assert any(c.normalized_value == "bookings@smile-dental.sa" for c in res.contacts.contacts)
    assert res.structured_name == "Smile Dental Clinic"
    assert res.address == "King Fahd Rd, Riyadh" and res.opening_hours == "Sa-Th 09:00-21:00"


async def test_mx_check_detects_domains_without_mail(monkeypatch):
    import dns.asyncresolver
    import dns.resolver

    from app.research.enrichment.email_check import domain_accepts_mail

    class Rec:
        def __init__(self, exchange):
            self.exchange = exchange

    class FakeResolver:
        lifetime = 0

        async def resolve(self, domain, rtype):
            if domain == "good.sa" and rtype == "MX":
                return [Rec("mail.good.sa.")]
            if domain == "nullmx.sa" and rtype == "MX":
                return [Rec(".")]
            raise dns.resolver.NXDOMAIN()

    monkeypatch.setattr(dns.asyncresolver, "Resolver", FakeResolver)
    cache: dict = {}
    assert await domain_accepts_mail("good.sa", cache) is True
    assert await domain_accepts_mail("nullmx.sa", cache) is False
    assert await domain_accepts_mail("missing.sa", cache) is False
    assert cache == {"good.sa": True, "nullmx.sa": False, "missing.sa": False}


# ----------------------------------------------------------------------------- import

CSV_AR = (
    "الاسم,الموقع,الجوال,انستجرام,المدينة\n"
    "عيادة الابتسامة,smile-dental.sa,0112345678,smiledental,الرياض\n"
    ",nameless.sa,,,\n"
    "Only Name,,,,\n"
    "Insta Shop,instagram.com/shop,,@insta.shop,\n"
).encode("utf-8-sig")


def test_import_parses_arabic_headers_and_reports_rejections():
    rows, rejected = parse_import("list.csv", CSV_AR)
    assert [r["name"] for r in rows] == ["عيادة الابتسامة", "Insta Shop"]
    assert rows[0]["website"] == "https://smile-dental.sa"
    assert rows[0]["social_urls"] == ["https://www.instagram.com/smiledental"]
    assert rows[1]["website"] is None and "warning" in rows[1]  # a social URL is not a business website
    assert {r["line"]: r["reason"] for r in rejected} == {
        3: "missing name",
        4: "needs at least a website, phone, email or social profile",
    }
    with pytest.raises(ImportError_, match="name"):
        parse_import("x.csv", b"website\nhttps://a.sa\n")
    with pytest.raises(ImportError_, match="Unsupported"):
        parse_import("x.pdf", b"%PDF")


def test_import_reads_xlsx():
    import io

    from openpyxl import Workbook

    wb = Workbook()
    wb.active.append(["Name", "Website", "Phone"])
    wb.active.append(["Acme Clinic", "https://acme.sa/about", None])
    buf = io.BytesIO()
    wb.save(buf)
    rows, rejected = parse_import("list.xlsx", buf.getvalue())
    assert rows[0]["name"] == "Acme Clinic" and rejected == []


# ----------------------------------------------------------------------------- scraping parsers

MAPS_PLACE = """<html><body>
<h1 class="DUwDvf">Smile Dental Clinic</h1>
<div class="F7nice"><span aria-hidden="true">4.6</span><span aria-label="1,234 reviews">(1,234)</span></div>
<button jsaction="pane.rating.category">Dental clinic</button>
<button data-item-id="address" aria-label="Address: King Fahd Rd, Riyadh 12345"></button>
<a data-item-id="authority" href="https://smile-dental.sa/?utm_source=gmb"></a>
<button data-item-id="phone:tel:+966112345678" aria-label="Phone: 011 234 5678"></button>
<div class="t39EBf" aria-label="Saturday, 9 AM to 9 PM; Sunday, 9 AM to 9 PM. Hide open hours for the week"></div>
</body></html>"""
PLACE_URL = "https://www.google.com/maps/place/Smile/@24.7,46.6,17z/data=!3m1!4b1!4m6!3m5!1s0x3e2f:0xabc123!8m2!3d24.7136!4d46.6753"


def test_parse_maps_place():
    p = parse_maps_place(MAPS_PLACE, PLACE_URL)
    assert p.name == "Smile Dental Clinic" and p.category == "Dental clinic"
    assert (p.rating, p.reviews) == (4.6, 1234)
    assert p.address == "King Fahd Rd, Riyadh 12345"
    assert p.phone == "+966112345678"
    assert p.website.startswith("https://smile-dental.sa/")
    assert p.feature_id == "0x3e2f:0xabc123" == maps_feature_id(PLACE_URL)
    assert (p.lat, p.lng) == (24.7136, 46.6753)
    assert p.hours.startswith("Saturday") and "Hide" not in p.hours


def test_count_parsing_and_block_detection():
    assert parse_count("1,234") == 1234 and parse_count("12.5K") == 12500 and parse_count("3M") == 3_000_000
    assert parse_count("1,2K") == 1200 and parse_count(None) is None
    assert is_blocked("https://www.google.com/sorry/index?continue=x", "")
    assert is_blocked("https://www.google.com/maps", "<p>Our systems have detected unusual traffic</p>")
    assert not is_blocked("https://www.google.com/maps", MAPS_PLACE)


IG = """<html><head><meta property="og:title" content="Smile Dental (@smiledental) • Instagram photos and videos">
<meta property="og:description" content="12.5K Followers, 300 Following, 845 Posts - See Instagram photos and videos from Smile Dental (@smiledental)">
<meta name="description" content="12.5K Followers, 300 Following, 845 Posts - Smile Dental (@smiledental) on Instagram: &quot;Book: +966 50 123 4567 · info@smile-dental.sa&quot;">
</head></html>"""
FB = """<html><head><meta property="og:title" content="Smile Dental Clinic">
<meta property="og:description" content="Smile Dental Clinic. 8,901 likes · 40 talking about this · 120 were here. Family dentistry in Riyadh.">
</head></html>"""
SNAP = """<html><script id="__NEXT_DATA__" type="application/json">{"props":{"pageProps":{"userProfile":{
"publicProfileInfo":{"title":"Smile Dental","bio":"Riyadh dentist","subscriberCount":"5400",
"websiteUrl":"https://smile-dental.sa"}}}}}</script></html>"""
TT = """<html><script id="__UNIVERSAL_DATA_FOR_REHYDRATION__" type="application/json">{"__DEFAULT_SCOPE__":
{"webapp.user-detail":{"userInfo":{"user":{"nickname":"Smile","signature":"Smiles daily",
"bioLink":{"link":"smile-dental.sa"}},"stats":{"followerCount":2200,"heartCount":51000,"videoCount":87}}}}}</script></html>"""


def test_parse_public_social_profiles():
    ig = parse_social_profile("instagram", "https://www.instagram.com/smiledental", IG)
    assert (ig.followers, ig.following, ig.posts) == (12500, 300, 845) and ig.name == "Smile Dental"
    fb = parse_social_profile("facebook", "https://www.facebook.com/smile", FB)
    assert fb.likes == 8901 and fb.bio == "Family dentistry in Riyadh."
    sn = parse_social_profile("snapchat", "https://www.snapchat.com/add/smile", SNAP)
    assert (sn.followers, sn.website) == (5400, "https://smile-dental.sa")
    tt = parse_social_profile("tiktok", "https://www.tiktok.com/@smile", TT)
    assert (tt.followers, tt.likes, tt.posts, tt.website) == (2200, 51000, 87, "smile-dental.sa")
    wall = parse_social_profile(
        "instagram", "https://www.instagram.com/accounts/login/?next=/smile", "<title>Login • Instagram</title>"
    )
    assert not wall.accessible and "login" in wall.summary()


def test_tiktok_string_counters_do_not_break_summary():
    # Some TikTok page variants send counters as strings; this used to crash the whole enrichment run.
    page = TT.replace('"followerCount":2200', '"followerCount":"12.5K"').replace(
        '"heartCount":51000', '"heartCount":"51000"'
    )
    tt = parse_social_profile("tiktok", "https://www.tiktok.com/@smile", page)
    assert (tt.followers, tt.likes) == (12500, 51000)
    assert "12,500 followers" in tt.summary()


# ----------------------------------------------------------------------------- Google Maps provider (fake browser)


class FakePages:
    """Stands in for BrowserSession: serves synthetic pages, records visits."""

    def __init__(self, pages: dict[str, str], block_after: int | None = None) -> None:
        self.pages = pages
        self.visited: list[str] = []
        self.block_after = block_after
        self.closed = False
        self.sessions_used: list[str | None] = []
        self.login_walls: set[str] = set()

    async def open(self, url: str, wait_for: str | None = None, session: str | None = None) -> tuple[str, str]:
        if self.block_after is not None and len(self.visited) >= self.block_after:
            raise ScrapeBlocked("unusual traffic")
        self.visited.append(url)
        self.sessions_used.append(session)
        if session and session in self.login_walls:
            return "https://www.linkedin.com/checkpoint/challenge", "<html>checkpoint</html>"
        for key, html in self.pages.items():
            if key in url:
                return url, html
        return url, "<html></html>"

    async def scroll_feed(self, selector: str, max_rounds: int, stop_text: str | None = None) -> str:
        return self.pages["__feed__"]

    async def close(self) -> None:
        self.closed = True


FEED = (
    '<div role="feed">'
    '<a class="hfpxzc" href="https://www.google.com/maps/place/A/data=!4m2!3m1!1s0x1:0xa?hl=en"></a>'
    '<a class="hfpxzc" href="https://www.google.com/maps/place/B/data=!4m2!3m1!1s0x1:0xb?hl=en"></a>'
    '<a class="hfpxzc" href="https://www.google.com/maps/place/A/data=!4m2!3m1!1s0x1:0xa?hl=en"></a>'
    "</div>"
)


@pytest.fixture
def scraping_on(monkeypatch):
    monkeypatch.setattr(get_settings(), "scraping_enabled", True)


async def test_google_maps_disabled_by_default():
    assert GoogleMapsProvider().state(ctx()).status == ProviderStatus.DISABLED


async def test_google_maps_scrapes_places(scraping_on):
    place_b = MAPS_PLACE.replace("Smile Dental Clinic", "Bright Teeth").replace(
        'href="https://smile-dental.sa/?utm_source=gmb"', 'href="https://instagram.com/brightteeth"'
    )
    pages = FakePages({"/maps/search/": FEED, "__feed__": FEED, "0x1:0xa": MAPS_PLACE, "0x1:0xb": place_b})
    found = await GoogleMapsProvider(lambda country: pages).search_businesses(
        Q, ProviderContext({}, {"max_queries": 1})
    )
    assert [c.name for c in found] == ["Smile Dental Clinic", "Bright Teeth"]
    smile, bright = found
    assert smile.identifiers == {"gmaps": "0x1:0xa"} and smile.raw["rating"] == 4.6 and smile.raw["reviews"] == 1234
    assert smile.website_url == "https://smile-dental.sa" and smile.phone == "+966112345678"
    assert bright.website_url is None and bright.social_urls == ["https://instagram.com/brightteeth"]
    assert pages.closed and sum("/maps/place/" in v for v in pages.visited) == 2  # duplicate link opened once


async def test_google_maps_block_keeps_collected_or_fails_cleanly(scraping_on):
    pages = FakePages({"/maps/search/": FEED, "__feed__": FEED, "0x1:0xa": MAPS_PLACE}, block_after=2)
    found = await GoogleMapsProvider(lambda c: pages).search_businesses(Q, ProviderContext({}, {"max_queries": 1}))
    assert [c.name for c in found] == ["Smile Dental Clinic"]  # second place blocked; first kept
    blocked = FakePages({}, block_after=0)
    with pytest.raises(ProviderError, match="blocked"):
        await GoogleMapsProvider(lambda c: blocked).search_businesses(Q, ctx())


# ----------------------------------------------------------------------------- end to end: OSM + import + social


async def _run(campaign_id: str, site_transport, page_source) -> str:
    from app.core.db import get_sessionmaker
    from app.research.pipeline import execute_campaign

    async with get_sessionmaker()() as s:
        run = await s.scalar(
            select(CampaignRun)
            .where(CampaignRun.campaign_id == uuid.UUID(campaign_id))
            .order_by(CampaignRun.run_number.desc())
            .limit(1)
        )
        status = await execute_campaign(
            s, uuid.UUID(campaign_id), run.id, site_transport=site_transport, page_source=page_source
        )
        return status.value


async def test_real_campaign_with_osm_import_and_social_enrichment(client, dispatched, db, monkeypatch, scraping_on):
    from app.core import safe_http

    async def no_dns(self, url):
        return url

    async def fake_mx(domain, cache):
        return domain != "dead-mail.sa"

    monkeypatch.setattr(safe_http.SafeFetcher, "_check", no_dns)
    monkeypatch.setattr("app.research.pipeline.domain_accepts_mail", fake_mx)
    osm = get_discovery_provider("osm")
    monkeypatch.setattr(osm, "_transport", osm_transport())
    monkeypatch.setattr(osm, "_pause", 0)

    def site(request):
        if request.url.host == "smile-dental.sa" and request.url.path == "/":
            return httpx.Response(200, text=JSON_LD_PAGE, headers={"content-type": "text/html"})
        return httpx.Response(404, text="")

    csv_bytes = b"name,instagram,email\nGlow Studio,glowstudio,hello@dead-mail.sa\n"
    preview = await client.post(
        "/api/v1/campaigns/import-preview",
        json={"filename": "list.csv", "content_base64": base64.b64encode(csv_bytes).decode()},
    )
    assert preview.status_code == 200, preview.text
    encoded = preview.json()["encoded"]
    assert json.loads(encoded[0])["social_urls"] == ["https://www.instagram.com/glowstudio"]

    body = {
        "name": "Riyadh dentists (OSM)",
        "country": "SA",
        "city": "Riyadh",
        "industry": "dental_clinics",
        "sources": [{"provider_key": "osm"}, {"provider_key": "import", "manual_urls": encoded}],
        "settings": {"target_count": 10, "max_companies": 10, "min_score": 0},
    }
    r = await client.post("/api/v1/campaigns", json={**body, "start": True})
    assert r.status_code == 201, r.text
    camp = r.json()
    assert not camp["is_demo"]
    glow_ig = IG.replace("Smile Dental", "Glow Studio").replace("smiledental", "glowstudio")
    pages = FakePages({"instagram.com/smiledental": IG, "instagram.com/glowstudio": glow_ig})
    status = await _run(camp["id"], httpx.MockTransport(site), pages)
    assert status in ("completed", "partially_completed")

    ws = (await db.scalar(select(Business).where(Business.name == "Glow Studio"))).workspace_id
    smile = await db.scalar(
        select(Business).where(Business.workspace_id == ws, Business.normalized_domain == "smile-dental.sa")
    )
    assert smile.identifiers["osm"] == "node/2"
    assert smile.name == "Smile Dental"  # the listing name is kept; schema.org only names domain-only records
    contacts = (await db.scalars(select(BusinessContact).where(BusinessContact.business_id == smile.id))).all()
    providers = {(c.type, c.source_provider) for c in contacts}
    assert ("phone", "osm") in providers  # published on the map listing
    assert ("social", "osm") in providers and ("social", "website") in providers
    assert ("phone", "instagram") in providers  # only written in the Instagram bio (the email was on the site)
    evidence = (await db.scalars(select(BusinessEvidence).where(BusinessEvidence.business_id == smile.id))).all()
    kinds = {e.kind for e in evidence}
    assert {"listing", "social_profile", "page", "structured"} <= kinds
    ig = next(e for e in evidence if e.kind == "social_profile" and "instagram.com/smiledental" in e.url)
    assert "12,500 followers" in ig.excerpt

    glow = await db.scalar(select(Business).where(Business.workspace_id == ws, Business.name == "Glow Studio"))
    assert glow.identifiers == {"social": "https://www.instagram.com/glowstudio"}
    dead = await db.scalar(
        select(BusinessContact).where(
            BusinessContact.business_id == glow.id, BusinessContact.normalized_value == "hello@dead-mail.sa"
        )
    )
    assert dead.verification_status == VerificationStatus.INVALID  # MX check: domain receives no mail

    # Re-running the same campaign source must not duplicate OSM businesses that have no website/phone.
    nocontact = (
        await db.scalars(select(Business).where(Business.workspace_id == ws, Business.name == "No Contact Dental"))
    ).all()
    assert len(nocontact) == 1 and nocontact[0].identifiers == {"osm": "node/1"}

    lead = (await client.get(f"/api/v1/leads/{smile.id}")).json()
    assert lead["score"]["scoring_version"] == "1.1.0"
    assert any(e["kind"] == "social_profile" for e in lead["evidence"])


# ----------------------------------------------------------------------------- linked-account sessions

LI_COMPANY = """<html><head><meta property="og:description" content="Smile Dental | 3,210 followers on LinkedIn.">
</head><body>Hospitals and Health Care · Riyadh · 3,210 followers · 51-200 employees</body></html>"""


def test_session_state_validation_keeps_only_platform_cookies():
    from app.research.scraping.sessions import validate_state

    state = {
        "cookies": [{"name": "li_at", "domain": ".linkedin.com"}, {"name": "x", "domain": ".tracker.com"}],
        "origins": [{"origin": "https://www.linkedin.com"}, {"origin": "https://evil.example"}],
    }
    clean = validate_state("linkedin", state)
    assert [c["name"] for c in clean["cookies"]] == ["li_at"] and len(clean["origins"]) == 1
    with pytest.raises(ValueError, match="cookies"):
        validate_state("linkedin", {"cookies": [{"domain": ".tracker.com"}]})
    with pytest.raises(ValueError):
        validate_state("myspace", state)


def test_linkedin_company_page_parsing():
    p = parse_social_profile("linkedin", "https://www.linkedin.com/company/smile", LI_COMPANY)
    assert p.accessible and p.followers == 3210 and p.extra["employees"] == "51-200"
    # Real logged-in layout: big JSON blobs in <code> first, then the header text with abbreviated counts.
    big = (
        "<html><head><title>Acme: Overview | LinkedIn</title></head><body>"
        + "<code>"
        + '{"data": "'
        + "x" * 300_000
        + ' 5 followers"}'
        + "</code>"
        + "<main>Acme Software Development Riyadh 29M followers 10K+ employees</main></body></html>"
    )
    p = parse_social_profile("linkedin", "https://www.linkedin.com/company/acme/", big)
    assert p.followers == 29_000_000 and p.extra["employees"] == "10K+"
    gone = parse_social_profile("linkedin", "https://www.linkedin.com/company/unavailable/", "<html></html>")
    assert not gone.accessible and "unavailable" in gone.summary()


async def test_sessions_api_and_pipeline_use_with_expiry(
    client, platform_admin, dispatched, db, monkeypatch, scraping_on
):
    from app.core import safe_http

    async def no_dns(self, url):
        return url

    monkeypatch.setattr(safe_http.SafeFetcher, "_check", no_dns)
    monkeypatch.setattr("app.research.pipeline.domain_accepts_mail", lambda d, c: _true())
    quota = {"n": 0}

    async def fake_quota(ws, platform, limit):
        quota["n"] += 1
        return quota["n"] <= 1  # only the first logged-in visit fits today's cap

    monkeypatch.setattr("app.research.pipeline.take_quota", fake_quota)

    state = {"cookies": [{"name": "li_at", "value": "secret", "domain": ".linkedin.com", "path": "/"}], "origins": []}
    r = await client.post("/api/v1/providers/sessions/linkedin", json={"storage_state": state})
    assert r.status_code == 200, r.text
    listing = (await client.get("/api/v1/providers/sessions")).json()
    li = next(x for x in listing if x["platform"] == "linkedin")
    assert li["status"] == "connected" and li["daily_limit"] == 30
    assert "secret" not in r.text and "secret" not in str(listing)  # cookies are write-only
    bad = await client.post("/api/v1/providers/sessions/linkedin", json={"storage_state": {"cookies": []}})
    assert bad.status_code == 400

    rows = [
        {"name": "Smile Dental", "social_urls": ["https://www.linkedin.com/company/smile"], "line": 2},
        {"name": "Other Clinic", "social_urls": ["https://www.linkedin.com/company/other"], "line": 3},
        {"name": "Third Clinic", "social_urls": ["https://www.linkedin.com/company/third"], "line": 4},
    ]
    body = {
        "name": "Sessions",
        "country": "SA",
        "industry": "dental_clinics",
        "sources": [{"provider_key": "import", "manual_urls": [json.dumps(x) for x in rows]}],
        "settings": {"target_count": 5, "max_companies": 5, "min_score": 0, "concurrency": 1},
        "start": True,
    }
    camp = (await client.post("/api/v1/campaigns", json=body)).json()
    pages = FakePages({"linkedin.com/company/": LI_COMPANY})
    await _run(camp["id"], None, pages)
    # 1st visit logged in (cap allows one), the rest logged out after the cap was reached.
    assert pages.sessions_used[0] == "linkedin" and set(pages.sessions_used[1:]) == {None}
    ev = (await db.scalars(select(BusinessEvidence).where(BusinessEvidence.kind == "social_profile"))).all()
    assert any("3,210 followers" in (e.excerpt or "") and "51-200 employees" in (e.excerpt or "") for e in ev)

    # A logged-in visit that hits a checkpoint marks the session expired and stops using it.
    quota["n"] = 0
    camp2 = (await client.post("/api/v1/campaigns", json={**body, "name": "Sessions 2"})).json()
    walled = FakePages({"linkedin.com/company/": LI_COMPANY})
    walled.login_walls = {"linkedin"}
    # Fresh businesses would be deduped onto the first run's records; clear their profile evidence so they are
    # visited again.
    await db.execute(BusinessEvidence.__table__.delete().where(BusinessEvidence.kind == "social_profile"))
    await db.commit()
    await _run(camp2["id"], None, walled)
    listing = (await client.get("/api/v1/providers/sessions")).json()
    assert next(x for x in listing if x["platform"] == "linkedin")["status"] == "expired"
    events = (await client.get(f"/api/v1/campaigns/{camp2['id']}/events/history")).json()
    assert any(e["event_type"] == "session_expired" for e in events)

    assert (await client.delete("/api/v1/providers/sessions/linkedin")).status_code == 200
    listing = (await client.get("/api/v1/providers/sessions")).json()
    assert next(x for x in listing if x["platform"] == "linkedin")["status"] == "not_connected"


async def _true():
    return True


class FakeLoginBrowser:
    """Stands in for the login-browser service, including its check of the opaque login id."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict | None]] = []
        self.login_id: str | None = None
        self.platform: str | None = None
        self.state = {"cookies": [{"name": "bcookie", "domain": ".linkedin.com"}], "origins": []}

    async def __call__(self, path, body=None):
        from app.core.errors import AppError

        self.calls.append((path, body))
        if path == "/start":
            self.login_id, self.platform = body["login_id"], body["platform"]
            return {"platform": body["platform"], "vnc_password": "abc12345"}
        if body is None or body.get("login_id") != self.login_id:
            raise AppError("Login browser: this login was replaced or has ended", status_code=409)
        if path == "/capture":
            return {"platform": self.platform, "storage_state": self.state}
        self.login_id = self.platform = None
        return {"status": "cancelled"}


@pytest.fixture
async def login_browser(monkeypatch):
    from app.api.v1.providers import LOGIN_OWNER_KEY
    from app.core.redis import async_redis

    async def clear():
        r = async_redis()
        await r.delete(LOGIN_OWNER_KEY)
        await r.aclose()

    await clear()
    fake = FakeLoginBrowser()
    monkeypatch.setattr("app.api.v1.providers._login_browser", fake)
    yield fake
    await clear()


async def test_dashboard_login_flow_saves_only_logged_in_cookies(client, platform_admin, login_browser):
    calls = login_browser.calls
    r = await client.post("/api/v1/providers/sessions/linkedin/login/start")
    assert r.status_code == 200
    assert r.json()["viewer_url"].endswith("password=abc12345") and "autoconnect=1" in r.json()["viewer_url"]
    # Anonymous cookies only (no li_at): refused, so a half-finished login is never saved as "connected".
    r = await client.post("/api/v1/providers/sessions/linkedin/login/finish")
    assert r.status_code == 400 and "Not logged in" in r.text
    assert (await client.post("/api/v1/providers/sessions/tiktok/login/finish")).status_code == 409  # wrong platform
    login_browser.state["cookies"].append({"name": "li_at", "value": "tok", "domain": ".linkedin.com"})
    r = await client.post("/api/v1/providers/sessions/linkedin/login/finish")
    assert r.status_code == 200 and r.json()["status"] == "connected"
    # A successful save closed the login and released it.
    assert (await client.post("/api/v1/providers/sessions/linkedin/login/cancel")).status_code == 409
    # Refused save keeps the window open; a successful save closes it.
    assert [c[0] for c in calls] == ["/start", "/capture", "/capture", "/cancel"]
    assert len({c[1]["login_id"] for c in calls}) == 1


async def test_login_browser_is_bound_to_the_user_who_started_it(app, client, db, platform_admin, login_browser):
    from app.models.enums import Role
    from tests.conftest import login, make_user

    owner = platform_admin
    other_user, _ = await make_user(db)  # another platform admin, in another workspace
    teammate, _ = await make_user(db, role=Role.ADMIN, workspace=owner[1])  # same workspace, different user
    other_user.is_superuser = teammate.is_superuser = True
    await db.commit()
    other = await login(app, other_user.email)
    mate = await login(app, teammate.email)
    try:
        assert (await client.post("/api/v1/providers/sessions/linkedin/login/start")).status_code == 200
        login_browser.state["cookies"].append({"name": "li_at", "value": "victim", "domain": ".linkedin.com"})

        # Someone else can neither capture the victim's cookies, close the login, nor take the browser over.
        for c in (other, mate):
            assert (await c.post("/api/v1/providers/sessions/linkedin/login/finish")).status_code == 403
            assert (await c.post("/api/v1/providers/sessions/linkedin/login/cancel")).status_code == 403
            assert (await c.post("/api/v1/providers/sessions/tiktok/login/start")).status_code == 409
        listing = (await other.get("/api/v1/providers/sessions")).json()
        assert next(x for x in listing if x["platform"] == "linkedin")["status"] == "not_connected"
        assert [c[0] for c in login_browser.calls] == ["/start"]

        # The owner of the login can still finish it.
        r = await client.post("/api/v1/providers/sessions/linkedin/login/finish")
        assert r.status_code == 200 and r.json()["status"] == "connected"
        # Once released, the browser is free for the next user.
        assert (await other.post("/api/v1/providers/sessions/tiktok/login/start")).status_code == 200
    finally:
        await other.aclose()
        await mate.aclose()
