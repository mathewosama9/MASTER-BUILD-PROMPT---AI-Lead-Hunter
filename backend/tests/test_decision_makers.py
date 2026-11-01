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
    assert role_rank("Branch Manager") == 1 and role_rank("Director") == 1
    # Department heads run a function, not the business (they count only when the seller targets them).
    assert role_rank("Marketing Manager") == 0 and role_rank("Art Director") == 0 and role_rank("Head of IT") == 0
    assert role_rank("مدير المبيعات") == 0 and role_rank("Founder & Head of Marketing") == 3
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
        DecisionMaker("Mona Ali", "Branch Manager", "website", "u1", "e", 0.6),
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


async def _run(
    client, monkeypatch, team_html: str, *, named: bool = True, mx=None, pages=None, council=None
) -> tuple[uuid.UUID, list[str]]:
    from app.core import safe_http
    from app.core.db import get_sessionmaker
    from app.research.pipeline import execute_campaign

    async def no_dns(self, url):
        return url

    async def mx_ok(domain, cache):
        return True

    monkeypatch.setattr(safe_http.SafeFetcher, "_check", no_dns)
    monkeypatch.setattr("app.research.pipeline.domain_accepts_mail", mx or mx_ok)
    assert (await client.put("/api/v1/settings", json={"allow_named_contacts": named})).status_code == 200

    def site(request: httpx.Request) -> httpx.Response:
        if pages and str(request.url) in pages:
            return httpx.Response(200, text=pages[str(request.url)], headers={"content-type": "text/html"})
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
            s,
            cid,
            run.id,
            site_transport=httpx.MockTransport(site),
            search_transport=httpx.MockTransport(brave),
            council_transport=httpx.MockTransport(council) if council else None,
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


async def test_one_linkedin_result_alone_is_not_enough_to_deliver(client, dispatched, db, monkeypatch, brave_on):
    cid, queries = await _run(client, monkeypatch, TEAM_EMPTY)
    assert "site:linkedin.com/in" in queries[0] and "(Owner OR" in queries[0]
    # One search result is one source: not verified, so not delivered (and the run says so).
    assert await _people(db, cid) == []
    events = (await db.scalars(select(JobEvent).where(JobEvent.campaign_id == cid))).all()
    assert any(e.data.get("t") == "decision_makers_rejected" for e in events)


# A reachable business (it has a phone), so the research council is asked about it.
TEAM_REACHABLE = '<html><body><h1>Our Team</h1><p>Call <a href="tel:+966114445566">011 444 5566</a></p></body></html>'
PRESS = (
    "<html><head><title>Riyadh clinics</title></head><body><p>Sara Al Harbi, founder of Smile Dental in Riyadh, "
    "opened a second branch.</p></body></html>"
)


def _perplexity(people, citations):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.perplexity.ai"
        import json as _json

        text = _json.dumps({"people": people})
        output = [
            {"type": "search_results", "results": [{"url": u, "title": "t"} for u in citations]},
            {"type": "message", "content": [{"type": "output_text", "text": text, "annotations": []}]},
        ]
        return httpx.Response(200, json={"output": output, "usage": {"cost": {"total_cost": 0.004}}})

    return handler


async def test_ai_research_plus_linkedin_proves_the_decision_maker(client, dispatched, db, monkeypatch, brave_on):
    monkeypatch.setattr(get_settings(), "perplexity_api_key", "p")
    sara = {"name": "Sara Al Harbi", "role": "Founder", "quote": "", "source_urls": ["https://press.example/smile"]}
    cid, _ = await _run(
        client,
        monkeypatch,
        TEAM_REACHABLE,
        pages={"https://press.example/smile": PRESS},
        council=_perplexity([sara], ["https://press.example/smile"]),
    )
    from app.models import CampaignLead

    biz_ids = select(CampaignLead.business_id).where(CampaignLead.campaign_id == cid)
    person = await db.scalar(
        select(BusinessContact).where(BusinessContact.business_id.in_(biz_ids), BusinessContact.type == "person")
    )
    assert person is not None and person.person_name == "Sara Al Harbi"
    assert person.verification_status == "verified"
    proofs = {p["url"] for p in person.evidence["proofs"]}
    assert proofs == {"https://www.linkedin.com/in/sara", "https://press.example/smile"}
    assert person.evidence["sources_count"] == 2

    # The customer sees only verified people; a stale unproven one (earlier runs) is hidden, and a channel
    # saved under that name is shown as a plain business contact.
    for row in (
        BusinessContact(
            business_id=person.business_id,
            type="person",
            value="Ali Omar",
            normalized_value="person:aliomar",
            person_name="Ali Omar",
            person_role="CEO",
            source_provider="website",
            verification_status="discovered",
        ),
        BusinessContact(
            business_id=person.business_id,
            type="email",
            value="ali@smile-dental.sa",
            subtype="decision_maker",
            normalized_value="ali@smile-dental.sa",
            person_name="Ali Omar",
            person_role="CEO",
            source_provider="website",
        ),
    ):
        db.add(row)
    await db.commit()
    lead = (await client.get(f"/api/v1/leads/{person.business_id}")).json()
    people = [c for c in lead["contacts"] if c["type"] == "person"]
    assert [c["person_name"] for c in people] == ["Sara Al Harbi"]
    assert set(people[0]["proof_links"]) == proofs and people[0]["sources_count"] == 2
    ali = next(c for c in lead["contacts"] if c["value"] == "ali@smile-dental.sa")
    assert ali["person_name"] is None and ali["subtype"] is None

    # Exports carry the verified decision maker (and never the unproven one).
    import csv
    import io

    export = await client.get(f"/api/v1/exports/campaigns/{cid}", params={"format": "csv"})
    rows = list(csv.DictReader(io.StringIO(export.content.decode("utf-8-sig"))))
    row = next(r for r in rows if r["Company"])
    assert row["Decision maker"] == "Sara Al Harbi" and row["Decision maker role"] == "Founder"
    assert row["Decision maker LinkedIn"] == "https://www.linkedin.com/in/sara"
    assert "https://press.example/smile" in row["Decision maker proof"]
    assert "Ali Omar" not in export.content.decode("utf-8-sig")


async def test_a_name_only_the_ai_gives_is_never_delivered(client, dispatched, db, monkeypatch):
    """No page we read names her with the business: an AI answer alone is not proof."""
    monkeypatch.setattr(get_settings(), "perplexity_api_key", "p")
    ghost = {"name": "Layla Hassan", "role": "Owner", "quote": "", "source_urls": ["https://invented.example/x"]}
    asked = []

    def council(request):
        asked.append(request.url.host)
        return _perplexity([ghost], [])(request)

    cid, _ = await _run(client, monkeypatch, TEAM_REACHABLE, council=council)
    assert asked == ["api.perplexity.ai"]
    assert await _people(db, cid) == []


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

    async def fake_verify(self, email):
        calls.append(f"verify:{email}")
        return {"status": "valid"}

    monkeypatch.setattr("app.research.pipeline.HunterClient.domain_search", fake_domain_search)
    monkeypatch.setattr("app.research.providers.hunter.HunterClient.email_finder", fake_email_finder)
    monkeypatch.setattr("app.research.providers.hunter.HunterClient.verify", fake_verify)
    return calls


async def test_paid_lookups_only_fill_what_free_sources_missed(client, dispatched, db, monkeypatch, hunter_calls):
    cid, _ = await _run(client, monkeypatch, TEAM_NAMED)
    # Named for free, but no direct channel: only Hunter's Email Finder runs for him (no domain search).
    assert hunter_calls == ["finder:Omar Khaled@smile-dental.sa", "verify:omar.khaled@smile-dental.sa"]
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


async def test_mail_check_never_touches_the_decision_maker_record(client, dispatched, db, monkeypatch):
    """A PERSON row's value is "person:<key>"; looking that up as a mail domain used to mark the person invalid."""
    looked_up: list[str] = []

    async def strict_mx(domain, cache):
        looked_up.append(domain)
        return "." in domain  # like real DNS: "person:omarkhaled" has no mail server

    cid, _ = await _run(client, monkeypatch, TEAM_NAMED, mx=strict_mx)
    from app.models import CampaignLead

    biz_ids = select(CampaignLead.business_id).where(CampaignLead.campaign_id == cid)
    person = await db.scalar(
        select(BusinessContact).where(BusinessContact.business_id.in_(biz_ids), BusinessContact.type == "person")
    )
    assert person is not None and person.verification_status != "invalid"
    assert not any(d.startswith("person:") for d in looked_up)


# ------------------------------------------------------------------------------ wrong people are rejected


def test_testimonials_and_client_quotes_are_not_the_business_people():
    from app.research.enrichment.decision_makers import from_cards

    html = """<section class="team"><div><h3>Dr. Omar Khaled</h3><p>Founder &amp; CEO</p></div></section>
      <section class="testimonials"><div><h4>John Smith</h4><p>CEO</p></div></section>
      <div id="our-clients"><h4>Laila Hassan</h4><p>Owner</p></div>
      <blockquote><h4>Sami Fares</h4><p>General Manager</p></blockquote>
      <div><h4>Nadia Ali</h4><p>CEO at Bright Teeth</p></div>"""
    found = {d.name for d in from_cards(html, "u", (), ("Smile Dental", "smile-dental.sa"))}
    assert found == {"Dr. Omar Khaled"}


def test_text_drops_people_written_as_working_for_another_company():
    text = (
        "Great service! – Mark Lee, CEO of Acme Logistics. Our founder: Sara Ali. Omar Khaled - Founder of Smile Dental"
    )
    found = {d.name for d in from_text(text, "u", "website", business_names=("Smile Dental Clinic",))}
    assert found == {"Sara Ali", "Omar Khaled"}


def test_names_lose_trailing_business_words_instead_of_being_dropped():
    assert clean_name("Sara Ali Dental Clinic") == "Sara Ali"
    assert clean_name("Omar Khaled Riyadh") == "Omar Khaled"


def test_one_shared_word_is_not_the_same_company():
    from app.research.enrichment.decision_makers import company_anchor

    assert company_anchor("CEO - Smile Dental", "Smile Dental Clinic")
    assert not company_anchor("CEO - Smile Logistics", "Smile Dental Clinic")  # "smile" alone used to pass
    assert company_anchor("Founder at smile-dental.sa", "Smile Dental Clinic", domain="smile-dental.sa")
    assert company_anchor("مدير عيادة النور", "عيادة النور")
    namesake = SearchHit("https://linkedin.com/in/o", "Omar Khaled - CEO - Smile Group | LinkedIn", "")
    assert from_linkedin_hit(namesake, "Smile Dental Clinic") is None


def test_former_roles_and_other_markets_are_rejected():
    from app.research.geo import country_place

    former = SearchHit("https://linkedin.com/in/o", "Omar Khaled - Former CEO - Smile Dental | LinkedIn", "")
    assert from_linkedin_hit(former, "Smile Dental") is None
    ex = SearchHit("https://linkedin.com/in/o", "Omar Khaled - Founder - Smile Dental | LinkedIn", "Cairo, Egypt")
    assert from_linkedin_hit(ex, "Smile Dental", place=country_place("SA")) is None
    here = SearchHit("https://linkedin.com/in/o", "Omar Khaled - Founder - Smile Dental | LinkedIn", "Riyadh, Saudi")
    assert from_linkedin_hit(here, "Smile Dental", place=country_place("SA")) is not None


def test_the_business_main_line_is_never_the_persons_direct_phone():
    from app.research.enrichment.decision_makers import contacts_in_snippet

    dm = DecisionMaker("Omar Khaled", "Founder", "website", "u", "e", 0.5)
    hit = SearchHit("https://instagram.com/omar", "Omar Khaled", "Book: +966 11 444 5566 · direct +966 50 111 2233")
    contacts_in_snippet(hit, dm, "SA", "smile-dental.sa", shared={"+966114445566"})
    assert dm.phone == "+966501112233"
