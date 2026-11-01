import httpx
import pytest

from app.core.safe_http import SafeFetcher, UnsafeURLError, validate_url_shape
from app.models.enums import ContactType, VerificationStatus
from app.research.enrichment.contacts import extract_contacts
from app.research.enrichment.website import research_website
from app.research.providers.base import SearchQuery
from app.research.providers.demo import DemoSiteTransport, demo_profiles

HTML = """
<html><body>
<a href="mailto:info@smile.sa">Email</a>
<p>Sales: sales@smile.sa — Dr. Personal: ahmad.k@smile.sa</p>
<a href="tel:+966115550123">Call</a>
<a href="https://wa.me/966500000001">WhatsApp</a>
<a href="https://www.instagram.com/smileclinic">IG</a>
<a href="https://www.facebook.com/sharer/sharer.php?u=x">share</a>
<a href="/contact-us">Contact us</a>
<img src="logo@2x.png">
<script>var e = "hidden@tracker.com";</script>
</body></html>
"""


def test_extracts_published_channels_only():
    res = extract_contacts(HTML, "https://smile.sa/", "SA", "smile.sa")
    by_type = {}
    for c in res.contacts:
        by_type.setdefault(c.type, []).append(c)
    emails = {c.normalized_value: c for c in by_type[ContactType.EMAIL]}
    assert set(emails) == {"info@smile.sa", "sales@smile.sa", "ahmad.k@smile.sa"}
    assert "hidden@tracker.com" not in emails  # script content is never parsed
    assert emails["info@smile.sa"].subtype == "general"
    assert emails["sales@smile.sa"].subtype == "sales"
    assert emails["ahmad.k@smile.sa"].subtype == "individual"
    assert emails["ahmad.k@smile.sa"].usage_restrictions  # personal data flagged
    # Published emails are discovered, never verified, until a provider verifies them.
    assert all(c.verification_status == VerificationStatus.DISCOVERED for c in emails.values())
    assert by_type[ContactType.PHONE][0].normalized_value == "+966115550123"
    assert by_type[ContactType.WHATSAPP][0].normalized_value == "+966500000001"
    socials = [c.value for c in by_type[ContactType.SOCIAL]]
    assert socials == ["https://www.instagram.com/smileclinic"]
    assert by_type[ContactType.CONTACT_PAGE][0].value == "https://smile.sa/contact-us"


def test_no_contacts_returns_empty():
    assert extract_contacts("<html><body><p>Welcome</p></body></html>", "https://x.sa", "SA", "x.sa").contacts == []


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost/",
        "http://127.0.0.1/",
        "http://10.0.0.5/",
        "http://169.254.169.254/latest/meta-data",
        "http://[::1]/",
        "file:///etc/passwd",
        "http://user:pw@site.sa/",
        "http://site.sa:22/",
        "http://printer.local/",
        "gopher://x.sa/",
    ],
)
def test_ssrf_rejects_internal_urls(url):
    with pytest.raises(UnsafeURLError):
        validate_url_shape(url)


class _RecordingBackend:
    def __init__(self) -> None:
        self.dialled: list[str] = []

    async def connect_tcp(self, host, port, **kwargs):
        import httpcore

        self.dialled.append(host)
        raise httpcore.ConnectError("test: not dialling out")

    async def sleep(self, seconds):
        return None


async def test_dns_rebinding_cannot_reach_internal_address(monkeypatch):
    """The name passes the pre-flight check, then re-resolves to loopback at connect time: refused."""
    from app.core import safe_http

    answers = iter([["93.184.216.34"], ["127.0.0.1"]])

    async def flipping_resolve(host):
        return next(answers)

    monkeypatch.setattr(safe_http, "_resolve", flipping_resolve)
    async with SafeFetcher(respect_robots=False) as f:
        with pytest.raises(UnsafeURLError):
            await f.get("http://rebind.example/")


async def test_connection_is_pinned_to_the_validated_address(monkeypatch):
    from app.core import safe_http

    async def resolve(host):
        return ["93.184.216.34"]

    monkeypatch.setattr(safe_http, "_resolve", resolve)
    inner = _RecordingBackend()
    transport = safe_http.pinned_transport()
    transport._pool._network_backend = safe_http.PinnedPublicBackend(inner)
    async with SafeFetcher(respect_robots=False, transport=transport) as f:
        with pytest.raises(httpx.ConnectError):
            await f.get("https://site.example/")
    assert inner.dialled == ["93.184.216.34"]  # the IP, never the hostname


async def test_redirect_to_private_address_is_blocked():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(302, headers={"location": "http://127.0.0.1/admin"})

    async with SafeFetcher(transport=httpx.MockTransport(handler), skip_dns_check=True) as f:
        with pytest.raises(UnsafeURLError):
            await f.get("https://public.example/")


async def test_robots_disallow_is_respected():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /")
        return httpx.Response(200, text="<html></html>", headers={"content-type": "text/html"})

    res = await research_website(
        "https://blocked.example/", country="SA", transport=httpx.MockTransport(handler), skip_dns_check=True
    )
    assert not res.reachable
    assert "robots" in (res.error or "")


async def test_oversized_responses_are_truncated(monkeypatch):
    big = "<html><body>" + ("x" * 3_000_000) + "</body></html>"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, text=big, headers={"content-type": "text/html"})

    async with SafeFetcher(transport=httpx.MockTransport(handler), skip_dns_check=True) as f:
        r = await f.get("https://big.example/")
    assert len(r.text) <= f.max_bytes + 70_000


async def test_website_research_on_demo_fixture_detects_signals():
    q = SearchQuery(country="SA", city="Riyadh", industry="dental_clinics", limit=5)
    profiles = demo_profiles(q, "seed")
    p = next(p for p in profiles if p["has_whatsapp"] and not p["no_contacts"])
    res = await research_website(
        f"https://{p['domain']}", country="SA", transport=DemoSiteTransport({p["domain"]: p}, "SA"), skip_dns_check=True
    )
    assert res.reachable
    kinds = {pg.kind for pg in res.pages}
    assert {"home", "about", "services", "contact"} <= kinds
    sig = {s.key: s for s in res.signals}
    assert sig["whatsapp_link"].observed and sig["whatsapp_link"].url
    assert sig["online_booking"].observed == p["has_booking"]
    # Absence is "not observed", never "missing"
    assert all(s.observed in (True, False) for s in res.signals)
    assert any(c.type == ContactType.WHATSAPP for c in res.contacts.contacts)
