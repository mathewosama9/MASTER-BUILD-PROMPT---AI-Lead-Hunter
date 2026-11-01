"""Decision-maker discovery: free sources (site data, page text, bios), then keyed sources (Brave/LinkedIn)."""

import httpx

from app.research.enrichment.decision_makers import (
    DecisionMaker,
    clean_name,
    extract_with_ai,
    from_json_ld,
    from_linkedin_hit,
    from_text,
    linkedin_query,
    merge,
    role_rank,
    search_linkedin,
)
from app.research.enrichment.social_search import SearchHit


def test_role_ranks_put_owners_above_managers_in_both_languages():
    assert role_rank("Founder & CEO") == 3 and role_rank("المؤسس") == 3 and role_rank("مالك العيادة") == 3
    assert role_rank("Medical Director") == 2 and role_rank("المدير الطبي") == 2
    assert role_rank("Marketing Manager") == 1
    assert role_rank("Receptionist") == 0 and role_rank("أخصائي تقويم") == 0


def test_clean_name_rejects_headings_and_single_words():
    assert clean_name(" Dr. Ahmed Ali ") == "Dr. Ahmed Ali"
    assert clean_name("د. أحمد علي") == "د. أحمد علي"
    assert clean_name("Ahmed") is None
    assert clean_name("About Our Team") is None
    assert clean_name("Riyadh Branch 2") is None


def test_text_patterns_in_both_orders_and_languages():
    text = "Welcome. Founder: Sara Al Harbi. Meet Dr. Omar Khaled – Medical Director. المدير الطبي - د. أحمد علي"
    found = {(d.name, d.role) for d in from_text(text, "https://x.sa/about", "website")}
    assert ("Sara Al Harbi", "Founder") in found
    assert ("Dr. Omar Khaled", "Medical Director") in found
    assert ("د. أحمد علي", "المدير الطبي") in found


def test_text_without_roles_or_with_staff_titles_names_nobody():
    assert from_text("Our friendly team: Nurse Mona, receptionist Ali. Book now - Director's choice", "u", "w") == []


def test_json_ld_person_and_founder():
    html = """<script type="application/ld+json">{"@graph":[
      {"@type":"Dentist","name":"Smile","founder":{"@type":"Person","name":"Sara Al Harbi"}},
      {"@type":"Person","name":"Omar Khaled","jobTitle":"General Manager"},
      {"@type":"Person","name":"Mona Ali","jobTitle":"Hygienist"}]}</script>"""
    found = {(d.name, d.role, d.source) for d in from_json_ld(html, "https://smile.sa")}
    assert found == {
        ("Sara Al Harbi", "Founder", "structured_data"),
        ("Omar Khaled", "General Manager", "structured_data"),
    }


class _FakeAI:
    def __init__(self, people):
        self.people = people

    async def structured(self, system, user, schema):
        from app.research.analysis.ai_service import AIResult

        return AIResult(schema(people=self.people), "deepseek", "m", 10, 10, 0.001)


async def test_ai_extraction_keeps_only_people_written_in_the_pages():
    pages = [("https://smile.sa/team", "Our team. Dr. Omar Khaled, Clinic Owner since 2010. Nurse Mona.")]
    ai = _FakeAI(
        [
            {"name": "Dr. Omar Khaled", "role": "Clinic Owner", "quote": "Dr. Omar Khaled, Clinic Owner"},
            {"name": "Invented Person", "role": "CEO", "quote": "Invented Person, CEO"},  # not in the page
            {"name": "Nurse Mona", "role": "Nurse", "quote": "Nurse Mona"},  # not a decision role
        ]
    )
    found, cost = await extract_with_ai(ai, "Smile Dental", pages)
    assert [(d.name, d.role, d.source_url) for d in found] == [
        ("Dr. Omar Khaled", "Clinic Owner", "https://smile.sa/team")
    ]
    assert cost == 0.001


def test_linkedin_hits_must_name_the_business_and_a_decision_role():
    ok = SearchHit("https://sa.linkedin.com/in/omar-khaled-123/", "Omar Khaled - CEO - Smile Dental | LinkedIn", "")
    dm = from_linkedin_hit(ok, "Smile Dental Clinic")
    assert dm and (dm.name, dm.role, dm.linkedin_url) == (
        "Omar Khaled",
        "CEO",
        "https://www.linkedin.com/in/omar-khaled-123",
    )
    other_company = SearchHit("https://linkedin.com/in/x", "Omar Khaled - CEO - Bright Teeth | LinkedIn", "")
    assert from_linkedin_hit(other_company, "Smile Dental Clinic") is None
    not_decision = SearchHit("https://linkedin.com/in/y", "Mona Ali - Hygienist - Smile Dental | LinkedIn", "")
    assert from_linkedin_hit(not_decision, "Smile Dental Clinic") is None
    company_page = SearchHit("https://linkedin.com/company/smile", "Smile Dental - CEO | LinkedIn", "")
    assert from_linkedin_hit(company_page, "Smile Dental") is None


async def test_search_linkedin_uses_brave_with_one_query():
    seen = []

    def brave(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.params["q"])
        hit = {"url": "https://www.linkedin.com/in/omar", "title": "Omar Khaled – Founder – Smile Dental | LinkedIn"}
        return httpx.Response(200, json={"web": {"results": [hit]}})

    found = await search_linkedin("Smile Dental", "k", transport=httpx.MockTransport(brave))
    assert [(d.name, d.role) for d in found] == [("Omar Khaled", "Founder")]
    assert seen == [linkedin_query("Smile Dental")] and "site:linkedin.com/in" in seen[0]


def test_merge_combines_sources_and_ranks_owner_first():
    people = [
        DecisionMaker("Mona Ali", "Marketing Manager", "website", "u1", "e", 0.6),
        DecisionMaker("Dr. Omar Khaled", "Director", "website", "u1", "e", 0.6),
        DecisionMaker("Omar Khaled", "Founder", "linkedin_search", "u2", "e", 0.55, linkedin_url="li"),
    ]
    merged = merge(people)
    top = merged[0]
    assert top.role == "Founder" and top.linkedin_url == "li"
    assert sorted(top.sources) == ["linkedin_search", "website"] and round(top.confidence, 2) == 0.7
    assert [d.name for d in merged][1] == "Mona Ali"


# ----------------------------------------------------------------------------- in a real campaign run

import uuid  # noqa: E402

import pytest  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.models import BusinessContact, CampaignRun, JobEvent  # noqa: E402

HOME = '<html><head><title>Smile Dental</title></head><body><a href="/our-team">Our team</a> Welcome</body></html>'
TEAM_NAMED = "<html><body><h1>Our Team</h1><p>Dr. Omar Khaled – Medical Director</p><p>Nurse Mona</p></body></html>"
TEAM_EMPTY = "<html><body><h1>Our Team</h1><p>Friendly dentists and nurses.</p></body></html>"


@pytest.fixture
def brave_on(monkeypatch):
    monkeypatch.setattr(get_settings(), "brave_api_key", "k")


async def _run(client, monkeypatch, team_html: str, *, named: bool = True) -> tuple[uuid.UUID, list[str]]:
    from app.core import safe_http
    from app.core.db import get_sessionmaker
    from app.research.pipeline import execute_campaign

    async def no_dns(self, url):
        return url

    async def mx_ok(domain, cache):
        return True

    monkeypatch.setattr(safe_http.SafeFetcher, "_check", no_dns)
    monkeypatch.setattr("app.research.pipeline.domain_accepts_mail", mx_ok)
    assert (await client.put("/api/v1/settings", json={"allow_named_contacts": named})).status_code == 200

    def site(request: httpx.Request) -> httpx.Response:
        if request.url.host != "smile-dental.sa":
            return httpx.Response(404)
        if request.url.path == "/":
            return httpx.Response(200, text=HOME, headers={"content-type": "text/html"})
        if request.url.path == "/our-team":
            return httpx.Response(200, text=team_html, headers={"content-type": "text/html"})
        return httpx.Response(404)

    queries: list[str] = []

    def brave(request: httpx.Request) -> httpx.Response:
        queries.append(request.url.params["q"])
        hit = {"url": "https://www.linkedin.com/in/sara", "title": "Sara Al Harbi - Founder - Smile Dental | LinkedIn"}
        return httpx.Response(200, json={"web": {"results": [hit]}})

    r = await client.post(
        "/api/v1/campaigns",
        json={
            "name": "DM",
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
    async with get_sessionmaker()() as s:
        run = await s.scalar(select(CampaignRun).where(CampaignRun.campaign_id == cid))
        await execute_campaign(
            s, cid, run.id, site_transport=httpx.MockTransport(site), search_transport=httpx.MockTransport(brave)
        )
    return cid, queries


async def _people(db, cid):
    from app.models import CampaignLead

    biz_ids = select(CampaignLead.business_id).where(CampaignLead.campaign_id == cid)
    rows = await db.scalars(
        select(BusinessContact).where(BusinessContact.business_id.in_(biz_ids), BusinessContact.type == "person")
    )
    return [(c.person_name, c.person_role, c.source_provider) for c in rows]


async def test_named_on_the_website_is_found_without_paid_lookups(client, dispatched, db, monkeypatch, brave_on):
    cid, queries = await _run(client, monkeypatch, TEAM_NAMED)
    assert await _people(db, cid) == [("Dr. Omar Khaled", "Medical Director", "website")]
    # The website named him, so no LinkedIn people search; only his own accounts are looked up by name.
    assert not any("(Owner OR" in q for q in queries)
    assert queries and all(q.startswith('"Omar Khaled" Smile Dental site:') for q in queries)
    events = (await db.scalars(select(JobEvent).where(JobEvent.campaign_id == cid))).all()
    assert any(e.data.get("t") == "decision_makers_done" for e in events)


async def test_unnamed_site_falls_back_to_linkedin_via_brave(client, dispatched, db, monkeypatch, brave_on):
    cid, queries = await _run(client, monkeypatch, TEAM_EMPTY)
    assert await _people(db, cid) == [("Sara Al Harbi", "Founder", "linkedin_search")]
    assert "site:linkedin.com/in" in queries[0] and "(Owner OR" in queries[0]
    # Her LinkedIn profile is already known, so it is not searched again.
    assert not any(q.startswith('"Sara Al Harbi"') and "linkedin" in q for q in queries[1:])


async def test_decision_makers_are_always_on_whatever_the_old_setting(client, dispatched, db, monkeypatch, brave_on):
    cid, _ = await _run(client, monkeypatch, TEAM_NAMED, named=False)
    assert await _people(db, cid) == [("Dr. Omar Khaled", "Medical Director", "website")]
    events = (await db.scalars(select(JobEvent).where(JobEvent.campaign_id == cid))).all()
    assert "decision_makers_disabled" not in [e.data.get("t") for e in events]


@pytest.fixture
def hunter_calls(monkeypatch):
    """Hunter connected; record every paid lookup instead of calling the API."""
    monkeypatch.setattr(get_settings(), "hunter_api_key", "h")
    calls: list[str] = []

    async def fake_domain_search(self, domain, include_personal=False):
        calls.append(f"domain:{domain}")
        return {"emails": []}

    async def fake_email_finder(self, domain, first, last):
        calls.append(f"finder:{first} {last}@{domain}")
        return {"email": "omar.khaled@smile-dental.sa", "score": 91, "sources": [{"uri": "https://x.sa/press"}]}

    monkeypatch.setattr("app.research.pipeline.HunterClient.domain_search", fake_domain_search)
    monkeypatch.setattr("app.research.providers.hunter.HunterClient.email_finder", fake_email_finder)
    return calls


async def test_paid_lookups_only_fill_what_free_sources_missed(client, dispatched, db, monkeypatch, hunter_calls):
    cid, _ = await _run(client, monkeypatch, TEAM_NAMED)
    # Named for free, but no direct channel: only Hunter's Email Finder runs for him (no domain search).
    assert hunter_calls == ["finder:Omar Khaled@smile-dental.sa"]
    rows = await _channels(db, cid)
    assert ("email", "omar.khaled@smile-dental.sa", "Dr. Omar Khaled", "hunter") in rows
    hunter_calls.clear()
    await _run(client, monkeypatch, TEAM_EMPTY)
    assert hunter_calls == ["domain:smile-dental.sa"]  # nobody named for free (and no Brave key)


TEAM_CARDS = """<html><body><h1>Leadership</h1>
<div class="card"><h3>Dr. Omar Khaled</h3><p>Founder &amp; CEO</p>
  <a href="mailto:omar@smile-dental.sa">Email</a> <a href="https://wa.me/966501112233">WhatsApp</a>
  <a href="https://www.linkedin.com/in/omar-khaled-dds">LinkedIn</a></div>
<div class="card"><h3>Mona Saeed</h3><p>Operations Manager</p><a href="tel:+966502223344">Call</a></div>
<footer>Clinic line <a href="tel:+966114445566">011 444 5566</a>
 · <a href="mailto:info@smile-dental.sa">info</a></footer>
</body></html>"""


async def test_contacts_printed_next_to_the_name_reach_the_person(client, dispatched, db, monkeypatch):
    cid, queries = await _run(client, monkeypatch, TEAM_CARDS)
    assert queries == []  # no Brave key: nothing searched, nothing paid
    rows = await _channels(db, cid)
    assert ("email", "omar@smile-dental.sa", "Dr. Omar Khaled", "website") in rows
    assert ("whatsapp", "+966501112233", "Dr. Omar Khaled", "website") in rows
    assert ("social", "https://www.linkedin.com/in/omar-khaled-dds", "Dr. Omar Khaled", "website") in rows
    assert ("phone", "+966502223344", "Mona Saeed", "website") in rows
    # The clinic's own line and info@ stay business contacts.
    assert not any(v in ("+966114445566", "info@smile-dental.sa") for _, v, n, _ in rows if n)


async def _channels(db, cid):
    from app.models import CampaignLead

    biz_ids = select(CampaignLead.business_id).where(CampaignLead.campaign_id == cid)
    rows = await db.scalars(
        select(BusinessContact).where(BusinessContact.business_id.in_(biz_ids), BusinessContact.type != "person")
    )
    return [
        (c.type, c.normalized_value if c.type != "social" else c.value, c.person_name, c.source_provider) for c in rows
    ]
