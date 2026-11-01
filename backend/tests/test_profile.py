"""Phase A: the workspace's own offerings and ideal customer drive analysis, scoring and pitches."""

from app.models.enums import Role
from app.research.analysis.heuristic import heuristic_analysis, template_pitch
from tests.conftest import login, make_user

SELLER = {
    "offerings": [
        {"id": "o_bot", "name": "بوت واتساب للرد الآلي", "description": "WhatsApp chatbot", "keywords": ["واتساب"]},
        {"id": "o_books", "name": "Bookkeeping", "description": "Monthly accounts", "keywords": ["accounting"]},
    ]
}
EVIDENCE = [
    {"id": "E1", "kind": "signal", "signal": "whatsapp_link", "label": "WhatsApp link", "observed": True},
    {"id": "E2", "kind": "signal", "signal": "live_chat", "label": "Live chat", "observed": False},
    {"id": "E3", "kind": "page", "title": "Home", "excerpt": "Smile dental clinic"},
]


async def test_profile_starts_empty_and_saves_offerings_with_stable_ids(client):
    r = await client.get("/api/v1/profile")
    assert r.status_code == 200 and r.json()["offerings"] == [] and r.json()["onboarding"]["completed"] is False
    body = {
        "company_name": "Codex",
        "business_category": "automation_ai",
        "offerings": [
            {"name": "WhatsApp bot", "keywords": ["واتساب", " "]},
            {"name": "whatsapp BOT"},  # duplicate name
            {"name": "CRM setup", "id": "o_crm"},
        ],
        "target_industries": ["dental_clinics", "Dental_Clinics", "مدارس خاصة"],
        "tone": "friendly",
    }
    r = await client.put("/api/v1/profile", json=body)
    assert r.status_code == 200, r.text
    data = r.json()
    assert [o["name"] for o in data["offerings"]] == ["WhatsApp bot", "CRM setup"]
    assert data["offerings"][1]["id"] == "o_crm" and data["offerings"][0]["id"].startswith("o_")
    assert data["offerings"][0]["keywords"] == ["واتساب"]
    assert data["target_industries"] == ["dental_clinics", "مدارس خاصة"] and data["tone"] == "friendly"
    again = (await client.get("/api/v1/profile")).json()
    assert again["offerings"] == data["offerings"]  # ids stay put between saves


async def test_only_admins_edit_the_profile(app, db, owner):
    viewer, _ = await make_user(db, role=Role.VIEWER, workspace=owner[1])
    c = await login(app, viewer.email)
    assert (await c.get("/api/v1/profile")).status_code == 200
    assert (await c.put("/api/v1/profile", json={"company_name": "x"})).status_code == 403
    await c.aclose()


async def test_meta_lists_seller_categories_for_the_profile_form(client):
    meta = (await client.get("/api/v1/meta")).json()
    keys = {c["key"] for c in meta["provider_categories"]}
    assert {"marketing_agency", "medical_supplier", "other"} <= keys
    assert all("group" in i for i in meta["industries"])


def test_rule_based_analysis_recommends_only_what_the_seller_sells():
    a = heuristic_analysis(business={"name": "Smile"}, evidence=EVIDENCE, target={}, seller=SELLER)
    assert [r.service for r in a.recommended_services] == ["o_bot"]
    assert a.recommended_services[0].name == "بوت واتساب للرد الآلي"
    assert "بوت واتساب" in a.opportunity


def test_nothing_is_recommended_when_no_offering_fits():
    seller = {"offerings": [{"id": "o_books", "name": "Bookkeeping", "description": "", "keywords": []}]}
    a = heuristic_analysis(business={"name": "Smile"}, evidence=EVIDENCE, target={}, seller=seller)
    assert a.recommended_services == []


def test_template_pitch_names_the_sellers_offering():
    draft = template_pitch({"company": "Smile", "service": "o_bot", "service_name": "بوت واتساب"}, "ar")
    assert "بوت واتساب" in draft["email_body"] and "o_bot" not in draft["email_body"]


# ---- Onboarding: progress and the automatic first search ----

ICP = {"target_industries": ["dental_clinics"], "target_countries": ["SA"], "target_cities": ["Riyadh"]}


def _only_osm(monkeypatch):
    from app.models.enums import ProviderStatus
    from app.services.providers import ProviderState

    async def state(db, workspace_id, key):
        ok = key == "osm"
        return ProviderState(ProviderStatus.CONNECTED if ok else ProviderStatus.REQUIRES_API_KEY)

    monkeypatch.setattr("app.services.providers.provider_state", state)


async def test_onboarding_step_only_moves_forward_and_can_be_completed(client):
    assert (await client.put("/api/v1/profile", json={"onboarding_step": 2})).json()["onboarding"]["step"] == 2
    data = (await client.put("/api/v1/profile", json={"onboarding_step": 1})).json()
    assert data["onboarding"] == {"step": 2, "completed": False, "steps": 6}
    data = (await client.put("/api/v1/profile", json={"onboarding_completed": True})).json()
    assert data["onboarding"]["completed"] is True


async def test_first_search_needs_who_and_where(client):
    r = await client.post("/api/v1/profile/first-search")
    assert r.status_code == 400 and r.json()["error"]["code"] == "profile_incomplete"


async def test_first_search_starts_a_small_campaign_from_the_profile(client, dispatched, monkeypatch):
    _only_osm(monkeypatch)
    await client.put("/api/v1/profile", json={**ICP, "offerings": [{"name": "Booking bot", "id": "o_bot"}], "outreach_language": "ar"})
    r = await client.post("/api/v1/profile/first-search")
    assert r.status_code == 201, r.text
    c = r.json()
    assert c["status"] == "queued" and len(dispatched) == 1
    assert (c["country"], c["city"], c["industry"], c["language"]) == ("SA", "Riyadh", "dental_clinics", "ar")
    assert [s["provider_key"] for s in c["sources"]] == ["osm"]
    assert c["services"] == ["o_bot"] and c["settings"]["target_count"] == 15
    assert (await client.get("/api/v1/profile")).json()["onboarding"]["completed"] is True


async def test_first_search_reports_when_no_source_is_available(client, dispatched, monkeypatch):
    from app.models.enums import ProviderStatus
    from app.services.providers import ProviderState

    async def state(db, workspace_id, key):
        return ProviderState(ProviderStatus.REQUIRES_API_KEY)

    monkeypatch.setattr("app.services.providers.provider_state", state)
    await client.put("/api/v1/profile", json=ICP)
    r = await client.post("/api/v1/profile/first-search")
    assert r.status_code == 503 and r.json()["error"]["code"] == "no_sources" and dispatched == []


async def test_first_search_creates_nothing_without_credits(app, db, dispatched, monkeypatch):
    _only_osm(monkeypatch)
    user, ws = await make_user(db, billing_exempt=False)
    c = await login(app, user.email)
    await c.put("/api/v1/profile", json=ICP)
    r = await c.post("/api/v1/profile/first-search")
    assert r.status_code in (402, 403), r.text
    assert (await c.get("/api/v1/campaigns")).json()["total"] == 0 and dispatched == []
    await c.aclose()
