"""Deeper discovery (directories, social profiles, any governorate) and decision-maker contact finding."""

import json

import httpx
import pytest

from app.research.catalog import decision_roles, directory_sites, place_names
from app.research.enrichment import people_finders
from app.research.enrichment.decision_makers import (
    DecisionMaker,
    email_matches_name,
    from_cards,
    match_person_hit,
    merge,
    personal_profile,
    search_person_profiles,
)
from app.research.enrichment.social_search import SearchHit
from app.research.providers.base import ProviderContext, ProviderError, SearchQuery
from app.research.providers.directories import DirectoryProvider
from app.research.providers.queries import build_search_queries
from app.research.providers.social_discovery import SocialDiscoveryProvider, name_from_title

# ------------------------------------------------------------------------------------- any market / any role


def test_any_governorate_is_searched_as_typed_in_both_languages():
    assert place_names("EG", "المنوفية") == ("المنوفية", "المنوفية")
    assert place_names("EG", "Cairo") == ("Cairo", "القاهرة")
    assert place_names("EG", None, "Sharqia") == ("Sharqia", "Sharqia")
    assert place_names("EG", None) == ("Egypt", "مصر")
    queries = build_search_queries(
        SearchQuery(country="EG", city="المنوفية", industry="مدارس خاصة", language="ar"), max_queries=20
    )
    assert queries[0] == "مدارس خاصة في المنوفية"  # free-text Arabic industry + governorate, no country fallback


def test_queries_interleave_languages_and_use_keywords():
    q = SearchQuery(country="SA", city="Riyadh", industry="dental_clinics", keywords=["تقويم", "implants"])
    out = build_search_queries(q, max_queries=40)
    assert out[0].endswith("in Riyadh") and "الرياض" in out[1]
    assert "implants Riyadh" in out and "تقويم الرياض" in out


def test_roles_follow_what_the_seller_sells_and_the_prospect_industry():
    roles = decision_roles("dental_clinics", "medical_supplier", ["Head Nurse"])
    assert roles[0] == "Head Nurse" and "Procurement Manager" in roles and "Medical Director" in roles


def test_directories_are_data_per_country_and_group(monkeypatch):
    assert "vezeeta.com" in directory_sites("EG", "dental_clinics")
    assert "yellowpages.com.eg" in directory_sites("EG", "schools")
    assert "fresha.com" in directory_sites("AE", "beauty_salons")
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "directory_sites", "EG:education:schools.example.eg")
    assert "schools.example.eg" in directory_sites("EG", None, "education")


# ------------------------------------------------------------------------------ decision makers: free sources


def test_cards_with_the_title_under_the_name_in_any_industry():
    html = """<section><h2>إدارة المدرسة</h2>
      <div><h4>أحمد محمود سالم</h4><span>مدير المدرسة</span></div>
      <div><h4>Sara Ali</h4><p>Procurement Manager</p></div>
      <div><h4>General Manager</h4><p>Our team</p></div>
      <div><h4>Noura Alsalem</h4><p>Dr. Diana Shaath</p><p>Clinic Manager</p></div>
      <div><h4>Vidya Chamle</h4><p>Product Owner</p></div>
      <div><a>View Expertise</a><p>Head of Dermatology</p></div></section>"""
    found = {(d.name, d.role) for d in from_cards(html, "u", ("Procurement Manager",))}
    # Dr. Diana is named with the floor-manager title; Noura's next element is Diana's card, not a title.
    assert found == {
        ("أحمد محمود سالم", "مدير المدرسة"),
        ("Sara Ali", "Procurement Manager"),
        ("Dr. Diana Shaath", "Clinic Manager"),
    }


def test_email_belongs_to_a_name_without_ever_building_one():
    assert email_matches_name("ahmed.ali@x.com", "Dr. Ahmed Ali")
    assert email_matches_name("aali@x.com", "Ahmed Ali") and email_matches_name("ali@x.com", "Ahmed Ali")
    assert not email_matches_name("info@x.com", "Ahmed Ali")
    assert not email_matches_name("sara@x.com", "Ahmed Ali")
    assert not email_matches_name("ahmed@x.com", "أحمد علي")  # Arabic names are never transliterated


def test_personal_profiles_only():
    assert personal_profile("https://sa.linkedin.com/in/omar-k/") == ("linkedin", "https://www.linkedin.com/in/omar-k")
    assert personal_profile("https://www.linkedin.com/company/smile")[0] is None
    assert personal_profile("https://instagram.com/dr.omar")[0] == "instagram"


def test_person_hit_must_name_the_person_and_the_business():
    dm = DecisionMaker("Dr. Omar Khaled", "Founder", "website", "u", "e", 0.5)
    ok = SearchHit("https://www.instagram.com/dr.omarkhaled", "Omar Khaled (@dr.omarkhaled)", "Founder @smiledental")
    assert match_person_hit(ok, dm, "Smile Dental", "instagram", handles=["smiledental"])
    other = SearchHit("https://www.instagram.com/omar.k", "Omar Khaled (@omar.k)", "Footballer")
    assert match_person_hit(other, dm, "Smile Dental", "instagram") is None
    wrong_person = SearchHit("https://www.linkedin.com/in/x", "Sara Ali - Smile Dental | LinkedIn", "")
    assert match_person_hit(wrong_person, dm, "Smile Dental", "linkedin") is None


async def test_person_search_picks_up_contacts_shown_in_their_bio():
    def brave(request: httpx.Request) -> httpx.Response:
        q = request.url.params["q"]
        if "instagram.com" in q:
            hit = {
                "url": "https://www.instagram.com/dr.omarkhaled",
                "title": "Omar Khaled (@dr.omarkhaled) • Instagram",
                "description": "Founder of Smile Dental. omar.khaled@smile-dental.sa · +966 50 111 2233",
            }
            return httpx.Response(200, json={"web": {"results": [hit]}})
        return httpx.Response(200, json={"web": {"results": []}})

    dm = DecisionMaker("Dr. Omar Khaled", "Founder", "website", "u", "e", 0.5)
    calls = await search_person_profiles(
        dm,
        "Smile Dental",
        ["linkedin", "instagram"],
        "k",
        country="SA",
        domain="smile-dental.sa",
        transport=httpx.MockTransport(brave),
    )
    assert calls == 2
    assert dm.profiles == {"instagram": "https://www.instagram.com/dr.omarkhaled"}
    assert dm.email == "omar.khaled@smile-dental.sa" and dm.phone == "+966501112233"
    assert dm.channel_sources["email"] == "person_search"


def test_seller_target_role_ranks_with_a_gm_but_below_the_owner():
    people = [
        DecisionMaker("Sara Ali", "Procurement Manager", "website", "u", "e", 0.5),
        DecisionMaker("Omar Khaled", "Owner", "website", "u", "e", 0.5),
        DecisionMaker("Mona Saeed", "Marketing Manager", "website", "u", "e", 0.5),
    ]
    assert [d.name for d in merge(people, ("Procurement Manager",))] == ["Omar Khaled", "Sara Ali", "Mona Saeed"]


# ------------------------------------------------------------------------------------- paid people finders


def _ctx(log: list) -> ProviderContext:
    async def record(*args):
        log.append(args)

    return ProviderContext(credentials={"api_key": "k"}, settings={}, record_usage=record)


async def test_apollo_match_returns_email_phone_and_linkedin():
    seen = []

    def apollo(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.path, json.loads(request.content), request.headers["x-api-key"]))
        person = {
            "name": "Omar Khaled",
            "title": "Founder",
            "email": "omar@smile-dental.sa",
            "email_status": "verified",
            "linkedin_url": "https://www.linkedin.com/in/omar-k",
            "phone_numbers": [{"sanitized_number": "+966501112233"}],
        }
        return httpx.Response(200, json={"person": person})

    usage: list = []
    dm = DecisionMaker("Dr. Omar Khaled", "Founder", "website", "u", "e", 0.5)
    ok = await people_finders.find_contact(
        "apollo",
        _ctx(usage),
        dm,
        domain="smile-dental.sa",
        company="Smile",
        country="SA",
        transport=httpx.MockTransport(apollo),
    )
    assert ok and dm.email == "omar@smile-dental.sa" and dm.phone == "+966501112233"
    assert dm.profiles["linkedin"] == "https://www.linkedin.com/in/omar-k" and "apollo" in dm.sources
    assert seen[0][0] == "/api/v1/people/match" and seen[0][1]["domain"] == "smile-dental.sa" and seen[0][2] == "k"
    assert usage[0][:2] == ("apollo", "people_match")


async def test_lusha_skips_do_not_call_numbers():
    def lusha(request: httpx.Request) -> httpx.Response:
        assert request.url.params["firstName"] == "Omar" and request.headers["api_key"] == "k"
        data = {
            "emailAddresses": [{"email": "omar@smile-dental.sa"}],
            "phoneNumbers": [{"number": "+966 50 999 0000", "doNotCall": True}, {"number": "+966501112233"}],
            "company": {"name": "Smile Dental Clinic"},
        }
        return httpx.Response(200, json={"contact": {"data": data}})

    dm = DecisionMaker("Omar Khaled", "Owner", "website", "u", "e", 0.5)
    assert await people_finders.find_contact(
        "lusha",
        _ctx([]),
        dm,
        domain=None,
        company="Smile Dental",
        country="SA",
        transport=httpx.MockTransport(lusha),
    )
    assert dm.phone == "+966501112233" and dm.channel_sources["phone"] == "lusha"


async def test_finders_never_attribute_a_namesake_at_another_company():
    def lusha(request: httpx.Request) -> httpx.Response:
        data = {"phoneNumbers": [{"number": "+966501112233"}], "company": {"name": "Bright Teeth"}}
        return httpx.Response(200, json={"contact": {"data": data}})

    dm = DecisionMaker("Omar Khaled", "Owner", "website", "u", "e", 0.5)
    args = {"domain": None, "company": "Smile Dental", "country": "SA"}
    assert not await people_finders.find_contact("lusha", _ctx([]), dm, **args, transport=httpx.MockTransport(lusha))

    def lusha_no_employer(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"contact": {"data": {"phoneNumbers": [{"number": "+966501112233"}]}}})

    no_employer = httpx.MockTransport(lusha_no_employer)
    assert not await people_finders.find_contact("lusha", _ctx([]), dm, **args, transport=no_employer)

    def apollo(request: httpx.Request) -> httpx.Response:
        person = {
            "name": "Omar Khaled",
            "title": "Founder",
            "email": "omar@bright.sa",
            "email_status": "verified",
            "organization": {"name": "Bright Teeth", "primary_domain": "bright.sa"},
        }
        return httpx.Response(200, json={"person": person})

    assert not await people_finders.find_contact(
        "apollo",
        _ctx([]),
        dm,
        domain="smile-dental.sa",
        company="Smile",
        country="SA",
        transport=httpx.MockTransport(apollo),
    )
    assert not dm.has_direct_contact


async def test_guessed_emails_are_never_kept():
    def apollo(request: httpx.Request) -> httpx.Response:
        person = {"name": "Omar Khaled", "title": "Founder", "email": "omar@smile.sa", "email_status": "guessed"}
        return httpx.Response(200, json={"person": person})

    dm = DecisionMaker("Omar Khaled", "Owner", "website", "u", "e", 0.5)
    assert not await people_finders.find_contact(
        "apollo", _ctx([]), dm, domain="smile.sa", company="Smile", country="SA", transport=httpx.MockTransport(apollo)
    )

    def hunter(request: httpx.Request) -> httpx.Response:
        if "email-finder" in request.url.path:
            return httpx.Response(200, json={"data": {"email": "omar@smile.sa", "score": 95}})
        return httpx.Response(200, json={"data": {"status": "accept_all"}})  # verifier cannot confirm it

    assert not await people_finders.find_contact(
        "hunter", _ctx([]), dm, domain="smile.sa", company="Smile", country="SA", transport=httpx.MockTransport(hunter)
    )

    def low_score(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": {"email": "omar@smile.sa", "score": 40}})

    assert not await people_finders.find_contact(
        "hunter",
        _ctx([]),
        dm,
        domain="smile.sa",
        company="Smile",
        country="SA",
        transport=httpx.MockTransport(low_score),
    )
    assert not dm.has_direct_contact


async def test_finder_account_errors_are_raised_for_the_pipeline_to_stop_that_finder():
    def denied(request: httpx.Request) -> httpx.Response:
        return httpx.Response(402, json={})

    dm = DecisionMaker("Omar Khaled", "Owner", "website", "u", "e", 0.5)
    with pytest.raises(ProviderError) as exc:
        await people_finders.find_contact(
            "apollo", _ctx([]), dm, domain="x.sa", company="X", country="SA", transport=httpx.MockTransport(denied)
        )
    assert exc.value.status_code == 402


async def test_nothing_found_is_not_a_contact():
    def empty(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": {"email": None}})

    dm = DecisionMaker("Omar Khaled", "Owner", "website", "u", "e", 0.5)
    assert not await people_finders.find_contact(
        "hunter", _ctx([]), dm, domain="x.sa", company="X", country="SA", transport=httpx.MockTransport(empty)
    )
    assert not dm.has_direct_contact


# ----------------------------------------------------------------------------------- new discovery sources


def test_social_titles_become_business_names():
    assert name_from_title("Glow Beauty Salon (@glow.salon) • Instagram photos and videos") == "Glow Beauty Salon"
    assert name_from_title("صالون جلو | Facebook") == "صالون جلو"
    assert name_from_title("Glow Salon (@glowsalon) | TikTok") == "Glow Salon"
    assert name_from_title("مركز تفاصيل للتدريب • Fotos y vídeos de Instagram") == "مركز تفاصيل للتدريب"


async def test_social_discovery_keeps_relevant_profiles_only():
    queries = []

    def brave(request: httpx.Request) -> httpx.Response:
        queries.append(request.url.params["q"])
        results = [
            {
                "url": "https://www.instagram.com/glow.salon/",
                "title": "Glow Beauty Salon (@glow.salon) • Instagram photos and videos",
                "description": "صالون تجميل في القاهرة الجديدة · للحجز 01001234567",
            },
            {"url": "https://www.instagram.com/p/abc123/", "title": "post", "description": "salon"},
            {"url": "https://www.tiktok.com/@fan/video/1", "title": "best salon in Cairo", "description": "صالون مصر"},
            {"url": "https://www.tiktok.com/discover/salon-cairo", "title": "salons", "description": "صالون مصر"},
            {"url": "https://www.instagram.com/foodie/", "title": "Foodie (@foodie)", "description": "burgers"},
            {  # a salon, but nothing says it is in Egypt: Brave cannot localise EG, so it is not kept
                "url": "https://www.instagram.com/glam.ksa/",
                "title": "Glam Salon (@glam.ksa)",
                "description": "صالون تجميل نسائي",
            },
            {
                "url": "https://www.instagram.com/riyadh.glow/",
                "title": "Glow Riyadh",
                "description": "صالون تجميل الرياض",
            },
        ]
        return httpx.Response(200, json={"web": {"results": results}})

    provider = SocialDiscoveryProvider(transport=httpx.MockTransport(brave), pause=0)
    q = SearchQuery(country="EG", city="New Cairo", industry="beauty_salons", language="ar", limit=10)
    found = await provider.search_businesses(
        q, ProviderContext(credentials={"api_key": "k"}, settings={"max_queries": 2})
    )
    assert [(c.name, c.social_urls, c.phone) for c in found] == [
        ("Glow Beauty Salon", ["https://www.instagram.com/glow.salon"], "+201001234567")
    ]
    assert found[0].identifiers["social"] == "https://www.instagram.com/glow.salon"
    assert all("site:" in q for q in queries) and "القاهرة الجديدة" in queries[0]


LISTING = """<html><head><script type="application/ld+json">{"@context":"https://schema.org","@type":"ItemList",
"itemListElement":[{"@type":"ListItem","item":{"@type":"School","name":"Nile Language School",
"telephone":"+20 48 222 3344","url":"https://nileschool.edu.eg","address":{"addressLocality":"Shebin El Kom"}}},
{"@type":"ListItem","item":{"@type":"School","name":"Delta School","telephone":"0482221111",
"sameAs":["https://www.facebook.com/deltaschool"]}}]}</script></head><body></body></html>"""
SINGLE = "<html><body><h1>Smile Dental</h1><a href='tel:+966501112233'>Call</a></body></html>"


async def test_directory_listing_pages_give_structured_businesses():
    def brave(request: httpx.Request) -> httpx.Response:
        results = [
            {"url": "https://www.yellowpages.com.eg/en/category/schools/menofia", "title": "Schools in Menofia"},
            {"url": "https://www.yellowpages.com.eg/", "title": "home"},  # not a listing
            {"url": "https://other.com/x", "title": "x"},  # not this directory
        ]
        return httpx.Response(200, json={"web": {"results": results}})

    def site(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, text=LISTING, headers={"content-type": "text/html"})

    provider = DirectoryProvider(
        transport=httpx.MockTransport(brave), site_transport=httpx.MockTransport(site), pause=0
    )
    usage: list = []
    q = SearchQuery(country="EG", city="المنوفية", industry="schools", limit=10)
    found = await provider.search_businesses(q, _ctx(usage))
    by_name = {c.name: c for c in found}
    assert set(by_name) == {"Nile Language School", "Delta School"}
    assert by_name["Nile Language School"].website_url == "https://nileschool.edu.eg"
    assert by_name["Delta School"].social_urls == ["https://www.facebook.com/deltaschool"]
    assert all(c.source_provider == "directories" for c in found) and usage


def test_directory_page_without_data_needs_a_single_business_and_a_contact():
    p = DirectoryProvider()
    q = SearchQuery(country="SA", industry="dental_clinics")
    assert [c.phone for c in p.parse_listing(SINGLE, "https://vezeeta.com/x", "vezeeta.com", q)] == ["+966501112233"]
    assert p.parse_listing("<h1>A</h1><h1>B</h1>", "https://vezeeta.com/y", "vezeeta.com", q) == []


async def test_a_directory_that_challenges_the_crawler_is_dropped():
    def brave(request: httpx.Request) -> httpx.Response:
        results = [{"url": f"https://vezeeta.com/doctor/{i}", "title": "x"} for i in range(3)]
        return httpx.Response(200, json={"web": {"results": results}})

    hits = []

    def site(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        hits.append(request.url.path)
        return httpx.Response(403, text="Attention Required! | Cloudflare")

    provider = DirectoryProvider(
        transport=httpx.MockTransport(brave), site_transport=httpx.MockTransport(site), pause=0
    )
    found = await provider.search_businesses(SearchQuery(country="SA", industry="dental_clinics"), _ctx([]))
    assert found == [] and len(hits) == 1  # stopped after the first challenge


async def test_social_discovery_keeps_using_the_brave_key_on_every_query():
    keys = []

    def brave(request: httpx.Request) -> httpx.Response:
        keys.append(request.headers["X-Subscription-Token"])
        hit = {
            "url": f"https://www.instagram.com/salon{len(keys)}/",
            "title": "Salon",
            "description": "صالون تجميل مصر",
        }
        return httpx.Response(200, json={"web": {"results": [hit]}})

    provider = SocialDiscoveryProvider(transport=httpx.MockTransport(brave), pause=0)
    q = SearchQuery(country="EG", industry="beauty_salons", language="ar", limit=50)
    found = await provider.search_businesses(
        q, ProviderContext(credentials={"api_key": "k"}, settings={"max_queries": 4})
    )
    assert keys == ["k"] * 4 and found  # only instagram.com hits match instagram queries


async def test_directory_reads_the_businesses_a_list_page_links_to_first():
    def brave(request: httpx.Request) -> httpx.Response:
        results = [{"url": f"https://yellowpages.com.eg/ar/category/x/{i}", "title": "list"} for i in range(5)]
        return httpx.Response(200, json={"web": {"results": results}})

    profile = "<html><body><h1>Delta School</h1><a href='tel:0482221111'>Call</a></body></html>"
    listing = (
        "<html><body>" + "".join(f"<a href='/ar/profile/school-{i}/{i}'>s</a>" for i in range(3)) + "</body></html>"
    )
    read = []

    def site(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        read.append(request.url.path)
        body = profile if "/profile/" in request.url.path else listing
        return httpx.Response(200, text=body, headers={"content-type": "text/html"})

    provider = DirectoryProvider(
        transport=httpx.MockTransport(brave), site_transport=httpx.MockTransport(site), pause=0
    )
    q = SearchQuery(country="EG", industry="education", limit=10)
    await provider.search_businesses(q, ProviderContext(credentials={"api_key": "k"}, settings={"max_pages": 4}))
    assert read == ["/ar/category/x/0", "/ar/profile/school-0/0", "/ar/profile/school-1/1", "/ar/profile/school-2/2"]
