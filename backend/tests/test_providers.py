import httpx
import pytest

from app.models.enums import ProviderStatus
from app.research.analysis.ai_service import AIService, validate_grounding
from app.research.analysis.heuristic import heuristic_analysis
from app.research.analysis.schemas import BusinessAnalysis, ObservedSignal, ServiceRecommendation
from app.research.providers.base import ProviderContext, ProviderError, RateLimited, SearchQuery
from app.research.providers.brave import BraveSearchProvider
from app.research.providers.hunter import HunterDiscoverProvider
from app.research.providers.queries import build_search_queries
from app.research.providers.social import FacebookProvider, XProvider

Q = SearchQuery(country="SA", city="Riyadh", industry="dental_clinics", keywords=["تقويم"], limit=5)


def ctx(**creds) -> ProviderContext:
    usage = []

    async def record(*args):
        usage.append(args)

    c = ProviderContext(credentials=creds, settings={"max_queries": 2}, record_usage=record)
    c.usage = usage  # type: ignore[attr-defined]
    return c


def test_query_expansion_is_bilingual():
    qs = build_search_queries(Q, max_queries=10)
    assert any("Riyadh" in q for q in qs)
    assert any("الرياض" in q for q in qs)
    assert len(qs) == len({q.casefold() for q in qs})


def test_missing_key_reports_requires_api_key():
    assert BraveSearchProvider().state(ctx()).status == ProviderStatus.REQUIRES_API_KEY
    assert HunterDiscoverProvider().state(ctx()).status == ProviderStatus.REQUIRES_API_KEY
    assert XProvider().state(ctx()).status == ProviderStatus.REQUIRES_API_KEY


async def test_missing_key_never_returns_fake_results():
    with pytest.raises(ProviderError):
        await BraveSearchProvider().search_businesses(Q, ctx())


async def test_brave_normalizes_and_skips_social_hosts():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-Subscription-Token"] == "k"
        return httpx.Response(
            200,
            json={
                "query": {"more_results_available": False},
                "web": {
                    "results": [
                        {
                            "url": "https://www.smile.sa/ar/about",
                            "title": "Smile Dental | Riyadh",
                            "description": "<b>Best</b>",
                        },
                        {"url": "https://smile.sa/contact", "title": "Contact Smile"},
                        {"url": "https://www.facebook.com/smile", "title": "Smile on Facebook"},
                        {"url": "https://nova-dental.com.sa/", "title": "Nova Dental - Clinic"},
                    ]
                },
            },
        )

    c = ctx(api_key="k")
    found = await BraveSearchProvider(httpx.MockTransport(handler)).search_businesses(Q, c)
    assert [f.website_url for f in found] == ["https://www.smile.sa", "https://nova-dental.com.sa"]
    assert found[0].name == "Smile Dental"
    assert found[0].description == "Best"
    assert found[0].source_url == "https://www.smile.sa/ar/about"
    assert c.usage and c.usage[0][0] == "brave"


async def test_brave_rate_limit_raises_rate_limited():
    transport = httpx.MockTransport(lambda r: httpx.Response(429, headers={"retry-after": "2"}))
    with pytest.raises(RateLimited) as exc:
        await BraveSearchProvider(transport).search_businesses(Q, ctx(api_key="k"))
    assert exc.value.retry_after == 2.0


async def test_hunter_discover_maps_domains():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v2/discover"
        return httpx.Response(
            200,
            json={
                "data": [
                    {"domain": "smile.sa", "organization": "Smile"},
                    {"domain": "instagram.com", "organization": "IG"},
                ]
            },
        )

    found = await HunterDiscoverProvider(httpx.MockTransport(handler)).search_businesses(Q, ctx(api_key="h"))
    assert [f.website_url for f in found] == ["https://smile.sa"]


async def test_x_access_tier_error_is_reported_honestly():
    state = await XProvider(httpx.MockTransport(lambda r: httpx.Response(403))).test_connection(ctx(bearer_token="t"))
    assert state.status == ProviderStatus.REQUIRES_PERMISSION


async def test_x_depleted_credits_are_reported_honestly():
    state = await XProvider(httpx.MockTransport(lambda r: httpx.Response(402))).test_connection(ctx(bearer_token="t"))
    assert state.status == ProviderStatus.REQUIRES_PERMISSION
    assert "credits" in state.detail


async def test_account_block_from_a_real_run_sticks_until_a_successful_run(db, owner):
    from app.models import ProviderConfiguration
    from app.services import providers as svc

    ws = owner[1].id
    assert (await svc.provider_state(db, ws, "osm")).status == ProviderStatus.CONNECTED
    db.add(ProviderConfiguration(workspace_id=ws, provider_key="osm", settings={}))
    await db.flush()

    await svc.record_outcome(db, ws, "osm", ProviderStatus.REQUIRES_PERMISSION, "credits depleted")
    state = await svc.provider_state(db, ws, "osm")
    assert state.status == ProviderStatus.REQUIRES_PERMISSION and state.detail == "credits depleted"

    # A transient error does not block the source; a successful run clears the stored error.
    await svc.record_outcome(db, ws, "osm", ProviderStatus.ERROR, "timeout")
    assert (await svc.provider_state(db, ws, "osm")).status == ProviderStatus.CONNECTED
    await svc.record_outcome(db, ws, "osm", ProviderStatus.CONNECTED)
    cfg = await svc.get_config(db, ws, "osm")
    assert (cfg.last_status, cfg.last_error) == ("connected", None)


async def test_facebook_is_unsupported_but_accepts_manual_urls():
    fb = FacebookProvider()
    assert fb.state(ctx()).status == ProviderStatus.UNSUPPORTED
    q = Q.model_copy(
        update={"manual_urls": ["https://smile.sa|https://facebook.com/smile", "https://facebook.com/only-a-page"]}
    )
    found = await fb.search_businesses(q, ctx())
    assert len(found) == 1 and found[0].website_url == "https://smile.sa"


def test_grounding_strips_unknown_evidence_ids():
    a = BusinessAnalysis(
        business_summary="x",
        observed_signals=[
            ObservedSignal(signal="has form", evidence_ids=["E1", "E99"]),
            ObservedSignal(signal="invented", evidence_ids=["E42"]),
        ],
        hypotheses=[],
        potential_problems=[],
        unknowns=[],
        opportunity="",
        suggested_pitch="",
        recommended_services=[ServiceRecommendation(service="crm_integration", rationale="r", evidence_ids=["E7"])],
        confidence=3.0,
        industry_fit=-1,
        characteristics_fit=0.5,
    )
    out = validate_grounding(a, {"E1", "E2"})
    assert [s.signal for s in out.observed_signals] == ["has form"]
    assert out.observed_signals[0].evidence_ids == ["E1"]
    assert out.recommended_services[0].evidence_ids == []
    assert out.confidence == 1.0 and out.industry_fit == 0.0


def test_heuristic_reports_unknowns_instead_of_claiming_absence():
    evidence = [
        {"id": "E1", "kind": "signal", "signal": "online_booking", "label": "Online booking", "observed": False},
        {"id": "E2", "kind": "signal", "signal": "contact_form", "label": "Contact form", "observed": True},
        {"id": "E3", "kind": "page", "title": "Smile Dental", "excerpt": "dental clinic in Riyadh"},
    ]
    a = heuristic_analysis(
        business={"name": "Smile", "industry": "dental_clinics"},
        evidence=evidence,
        target={"industry": "dental_clinics", "services": ["appointment_automation"]},
    )
    assert a.recommended_services[0].service == "appointment_automation"
    assert any("booking" in u.lower() for u in a.unknowns)
    assert all(s.evidence_ids for s in a.observed_signals)


def test_ai_service_unavailable_without_keys():
    assert not AIService({}).available
