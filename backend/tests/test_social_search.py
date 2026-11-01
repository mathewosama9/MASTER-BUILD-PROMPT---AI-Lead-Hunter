"""Finding a business's social profiles by name when it published no link to them (Brave Search API)."""

import uuid

import httpx
import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.models import Business, BusinessContact, CampaignLead, CampaignRun, JobEvent
from app.research.enrichment.social_search import (
    NAME_ONLY_NOTE,
    SearchBlocked,
    SearchHit,
    best_match,
    build_query,
    match_hit,
    name_tokens,
    web_search,
)
from tests.test_free_sources_and_scraping import FB, JSON_LD_PAGE, FakePages


def brave_page(*hits: tuple[str, str, str]) -> dict:
    return {"web": {"results": [{"url": u, "title": t, "description": f"<b>{d}</b>"} for u, t, d in hits]}}


async def test_brave_results_become_hits_and_blocks_are_reported():
    def ok(request: httpx.Request) -> httpx.Response:
        assert request.headers["X-Subscription-Token"] == "k"
        return httpx.Response(200, json=brave_page(("https://www.facebook.com/smileclinic", "Smile", "Riyadh")))

    hits = await web_search("x", brave_key="k", transport=httpx.MockTransport(ok))
    assert hits == [SearchHit("https://www.facebook.com/smileclinic", "Smile", "Riyadh")]
    with pytest.raises(SearchBlocked):
        await web_search("x", brave_key="k", transport=httpx.MockTransport(lambda r: httpx.Response(429)))


def test_name_tokens_drop_generic_words_in_both_languages():
    assert name_tokens("Smile Dental Clinic") == ["smile"]
    assert name_tokens("عيادة النور لطب الأسنان") == ["نور"]


def test_strong_match_by_domain_or_phone():
    hit = SearchHit("https://www.facebook.com/SmileDentalRUH/", "Smile Dental Clinic", "Book at smile-dental.sa")
    m = match_hit(hit, "facebook", "Smile Dental Clinic", domain="smile-dental.sa")
    assert m and m.strong and m.url == "https://www.facebook.com/SmileDentalRUH" and m.confidence == 0.6
    by_phone = SearchHit("https://www.tiktok.com/@smile.ruh", "Smile (@smile.ruh)", "Call 011 234 5678")
    assert match_hit(by_phone, "tiktok", "Smile Dental", phones=["+966112345678"]).strong


def test_name_only_match_needs_two_words_or_the_handle():
    two_words = SearchHit("https://www.instagram.com/noor.smile", "Noor Smile Clinic (@noor.smile)", "")
    m = match_hit(two_words, "instagram", "Noor Smile Dental")
    assert m and not m.strong and m.confidence == 0.4
    handle = SearchHit("https://www.instagram.com/smiledental", "Instagram", "")
    assert match_hit(handle, "instagram", "Smile Dental")
    # A single common word is not enough: "Smile Bakery" is not "Smile Dental".
    other = SearchHit("https://www.instagram.com/smilebakery", "Smile Bakery (@smilebakery)", "Riyadh")
    assert match_hit(other, "instagram", "Smile Dental") is None


def test_wrong_platform_posts_and_unrelated_results_are_rejected():
    post = SearchHit("https://www.instagram.com/p/ABC/", "Smile Dental Clinic", "smile-dental.sa")
    assert match_hit(post, "instagram", "Smile Dental Clinic", domain="smile-dental.sa") is None
    fb = SearchHit("https://www.facebook.com/smiledental", "Smile Dental Clinic", "smile-dental.sa")
    assert match_hit(fb, "instagram", "Smile Dental Clinic", domain="smile-dental.sa") is None
    hits = [SearchHit("https://www.facebook.com/x", "Unrelated", ""), fb]
    assert best_match(hits, "facebook", "Smile Dental Clinic", domain="smile-dental.sa", phones=[]).strong


def test_query_targets_one_platform():
    assert build_query("Smile Dental", "Riyadh", "tiktok") == '"Smile Dental" Riyadh site:tiktok.com'


def test_name_only_note_asks_for_confirmation():
    assert "confirm" in NAME_ONLY_NOTE


# ----------------------------------------------------------------------------- end to end in a campaign


@pytest.fixture
def search_on(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "scraping_enabled", True)
    monkeypatch.setattr(s, "social_search_enabled", True)


@pytest.fixture
def brave_key(monkeypatch):
    monkeypatch.setattr(get_settings(), "brave_api_key", "k")


async def _run_site_campaign(client, monkeypatch, search) -> tuple[uuid.UUID, FakePages]:
    from app.core import safe_http
    from app.core.db import get_sessionmaker
    from app.research.pipeline import execute_campaign

    async def no_dns(self, url):
        return url

    async def mx_ok(domain, cache):
        return True

    monkeypatch.setattr(safe_http.SafeFetcher, "_check", no_dns)
    monkeypatch.setattr("app.research.pipeline.domain_accepts_mail", mx_ok)

    def site(request: httpx.Request) -> httpx.Response:
        if request.url.host == "smile-dental.sa" and request.url.path == "/":
            return httpx.Response(200, text=JSON_LD_PAGE, headers={"content-type": "text/html"})
        return httpx.Response(404, text="")

    r = await client.post(
        "/api/v1/campaigns",
        json={
            "name": "Search by name",
            "country": "SA",
            "city": "Riyadh",
            "industry": "dental_clinics",
            "sources": [{"provider_key": "manual", "manual_urls": ["https://smile-dental.sa"]}],
            "settings": {"target_count": 1, "max_companies": 1, "min_score": 0, "ai_analysis": False},
            "start": True,
        },
    )
    assert r.status_code == 201, r.text
    cid = uuid.UUID(r.json()["id"])
    pages = FakePages({"facebook.com/SmileDentalRUH": FB})
    async with get_sessionmaker()() as s:
        run = await s.scalar(select(CampaignRun).where(CampaignRun.campaign_id == cid))
        status = await execute_campaign(
            s,
            cid,
            run.id,
            site_transport=httpx.MockTransport(site),
            page_source=pages,
            search_transport=httpx.MockTransport(search),
        )
    assert status.value == "completed"  # name search never makes a campaign "partial"
    return cid, pages


async def test_campaign_finds_missing_profiles_by_name(client, dispatched, db, monkeypatch, search_on, brave_key):
    queries: list[str] = []

    def search(request: httpx.Request) -> httpx.Response:
        q = request.url.params["q"]
        queries.append(q)
        if "site:facebook.com" in q:  # the site published no Facebook link; this result names its domain
            hit = ("https://www.facebook.com/SmileDentalRUH", "Smile Dental Clinic | Facebook", "smile-dental.sa")
            return httpx.Response(200, json=brave_page(hit))
        hit = ("https://www.tiktok.com/@smilebakery", "Smile Bakery (@smilebakery)", "Riyadh")  # not this business
        return httpx.Response(200, json=brave_page(hit))

    cid, pages = await _run_site_campaign(client, monkeypatch, search)

    # Instagram and Snapchat were linked on the website, so only Facebook and TikTok were searched.
    business_queries = [q for q in queries if not q.startswith('"Smile Dental" (') and "linkedin.com/in" not in q]
    assert sorted(q.split("site:")[1] for q in business_queries) == ["facebook.com", "tiktok.com"]
    biz = await db.scalar(
        select(Business)
        .join(CampaignLead, CampaignLead.business_id == Business.id)
        .where(CampaignLead.campaign_id == cid)
    )
    found = (
        await db.scalars(
            select(BusinessContact).where(
                BusinessContact.business_id == biz.id, BusinessContact.source_provider == "social_search"
            )
        )
    ).all()
    assert [(c.subtype, c.value) for c in found] == [("facebook", "https://www.facebook.com/SmileDentalRUH")]
    assert found[0].usage_restrictions is None  # strong match: the result named the business's domain
    assert "facebook.com/SmileDentalRUH" in " ".join(pages.visited)  # and the profile was then read
    events = (await db.scalars(select(JobEvent).where(JobEvent.campaign_id == cid))).all()
    assert any(e.data.get("t") == "social_search_done" and e.data["p"]["count"] == 1 for e in events)


async def test_without_a_brave_key_search_is_skipped_with_a_note(client, dispatched, db, monkeypatch, search_on):
    calls: list[httpx.Request] = []

    def search(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(500)

    cid, _ = await _run_site_campaign(client, monkeypatch, search)
    assert calls == []
    events = (await db.scalars(select(JobEvent).where(JobEvent.campaign_id == cid))).all()
    assert [e.data.get("t") for e in events].count("social_search_needs_key") == 1
