"""Client campaigns run on the platform admin's research settings; credit packages are bought with PayPal."""

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models import Campaign, CreditPackage, TopUpRequest, Workspace
from app.models.enums import ProviderStatus
from app.services import credits as credit_svc
from app.services import paypal
from app.services.providers import ProviderState
from tests.conftest import login, make_user

pytestmark = pytest.mark.managed

CAMPAIGN = {"name": "Dental Riyadh", "country": "SA", "city": "Riyadh", "industry": "dental_clinics"}


def _connected(monkeypatch, keys=("osm", "brave")):
    async def state(db, workspace_id, key):
        return ProviderState(ProviderStatus.CONNECTED if key in keys else ProviderStatus.REQUIRES_API_KEY)

    monkeypatch.setattr("app.services.providers.provider_state", state)


@pytest.fixture
async def defaults(db):
    """Admin research settings for the test; restored afterwards (platform_settings is one shared row)."""
    s = await credit_svc.platform_settings(db)
    before = dict(s.research_defaults or {})
    s.research_defaults = {"sources": ["osm", "google_maps", "brave"], "concurrency": 2, "ai_analysis": False,
                           "companies_per_target": 3, "max_budget_usd": 9.0}
    await db.commit()
    yield s
    s.research_defaults = before
    await db.commit()


async def test_client_campaign_uses_the_admin_settings_not_its_own(client, defaults, monkeypatch):
    _connected(monkeypatch)
    body = {**CAMPAIGN, "sources": [{"provider_key": "hunter"}],
            "settings": {"target_count": 10, "concurrency": 10, "ai_analysis": True, "max_runtime_minutes": 5}}
    r = await client.post("/api/v1/campaigns", json=body)
    assert r.status_code == 201, r.text
    c = r.json()
    # Only the admin's sources that are connected; the client's own pick is ignored.
    assert [s["provider_key"] for s in c["sources"]] == ["brave", "osm"] or \
        sorted(s["provider_key"] for s in c["sources"]) == ["brave", "osm"]
    # Clients see their lead count only, not the platform's settings or costs.
    assert c["settings"] == {"target_count": 10} and c["cost_ai"] == 0


async def test_stored_settings_follow_the_admin(client, db, defaults, monkeypatch):
    _connected(monkeypatch)
    r = await client.post("/api/v1/campaigns", json={**CAMPAIGN, "settings": {"target_count": 10, "concurrency": 9}})
    campaign = await db.get(Campaign, uuid.UUID(r.json()["id"]))
    await db.refresh(campaign)
    s = campaign.settings
    assert (s["concurrency"], s["ai_analysis"], s["max_companies"], s["max_budget_usd"]) == (2, False, 30, 9.0)
    assert s["max_runtime_minutes"] is None  # runs until done


async def test_client_without_connected_sources_gets_a_clear_error(client, defaults, monkeypatch):
    _connected(monkeypatch, keys=())
    r = await client.post("/api/v1/campaigns", json=CAMPAIGN)
    assert r.status_code == 503 and r.json()["error"]["code"] == "no_sources"


async def test_estimate_hides_providers_and_costs_from_clients(client, defaults, monkeypatch):
    _connected(monkeypatch)
    e = (await client.post("/api/v1/campaigns/estimate", json=CAMPAIGN)).json()
    assert e["notes"] == [] and e["providers"] == {} and e["estimated_cost_usd"] is None


async def test_admin_edits_research_defaults(app, platform_admin, defaults):
    c = await login(app, platform_admin[0].email)
    s = (await c.get("/api/v1/admin/settings")).json()
    assert s["research_defaults"]["concurrency"] == 2
    s["research_defaults"] = {**s["research_defaults"], "sources": ["osm"], "max_runtime_minutes": None}
    r = await c.put("/api/v1/admin/settings", json=s)
    assert r.status_code == 200 and r.json()["research_defaults"]["sources"] == ["osm"]
    s["research_defaults"]["sources"] = ["demo"]  # fixtures are not a search source
    assert (await c.put("/api/v1/admin/settings", json=s)).status_code == 422
    await c.aclose()


# ---------------------------------------------------------------- PayPal


@pytest.fixture
async def usd_package(db):
    pkg = CreditPackage(name_ar="باقة", name_en="Pack", credits=500, price=Decimal("50.00"), currency="USD")
    db.add(pkg)
    await db.commit()
    yield pkg
    await db.delete(pkg)
    await db.commit()


@pytest.fixture
def fake_paypal(monkeypatch):
    calls = {"orders": [], "captures": []}

    async def creds(db):
        return {"client_id": "cid-1234567890", "client_secret": "sec-1234567890", "mode": "sandbox"}

    async def create_order(c, *, amount, currency, reference, description, locale):
        calls["orders"].append((amount, currency, reference))
        return f"ORD-{uuid.uuid4().hex[:12]}", "https://www.sandbox.paypal.com/checkoutnow?token=x"

    def order(order_id, value="50.00", currency="USD"):
        return {"id": order_id, "purchase_units": [{"payments": {"captures": [
            {"id": f"CAP-{order_id}", "status": "COMPLETED", "amount": {"currency_code": currency, "value": value}}]}}]}

    async def capture_order(c, order_id):
        calls["captures"].append(order_id)
        return calls.get("next_order") or order(order_id)

    monkeypatch.setattr(paypal, "credentials", creds)
    monkeypatch.setattr(paypal, "create_order", create_order)
    monkeypatch.setattr(paypal, "capture_order", capture_order)
    calls["order"] = order
    return calls


@pytest.fixture
async def buyer(app, db):
    user, ws = await make_user(db, billing_exempt=False)
    c = await login(app, user.email)
    yield c, ws
    await c.aclose()


async def test_paypal_purchase_adds_credits_once(buyer, db, usd_package, fake_paypal):
    c, ws = buyer
    assert (await c.get("/api/v1/billing/summary")).json()["paypal_enabled"] is True
    r = await c.post("/api/v1/billing/paypal/orders", json={"package_id": str(usd_package.id)})
    assert r.status_code == 201
    oid = r.json()["order_id"]
    assert fake_paypal["orders"][0][:2] == (Decimal("50.00"), "USD")
    # Return page and a repeat (refresh / webhook race) grant the credits exactly once.
    first = await c.post("/api/v1/billing/paypal/capture", json={"order_id": oid})
    again = await c.post("/api/v1/billing/paypal/capture", json={"order_id": oid})
    assert first.status_code == again.status_code == 200 and first.json()["status"] == "approved"
    assert fake_paypal["captures"] == [oid]
    w = await db.get(Workspace, ws.id)
    await db.refresh(w)
    assert w.credit_balance == 500
    assert not await credit_svc.on_trial(db, w)  # a purchase ends the trial
    # An unfinished checkout is not a request awaiting the admin's review.
    assert (await c.get("/api/v1/billing/summary")).json()["pending_topups"] == 0


async def test_paypal_amount_mismatch_grants_nothing(buyer, db, usd_package, fake_paypal):
    c, ws = buyer
    oid = (await c.post("/api/v1/billing/paypal/orders", json={"package_id": str(usd_package.id)})).json()["order_id"]
    fake_paypal["next_order"] = fake_paypal["order"](oid, value="5.00")
    r = await c.post("/api/v1/billing/paypal/capture", json={"order_id": oid})
    assert r.status_code == 502 and r.json()["error"]["code"] == "paypal_amount_mismatch"
    w = await db.get(Workspace, ws.id)
    await db.refresh(w)
    assert w.credit_balance == 0


async def test_cancelled_checkout_is_not_reviewable(app, buyer, db, usd_package, fake_paypal, platform_admin):
    c, ws = buyer
    oid = (await c.post("/api/v1/billing/paypal/orders", json={"package_id": str(usd_package.id)})).json()["order_id"]
    topup = await db.scalar(select(TopUpRequest).where(TopUpRequest.provider_order_id == oid))
    admin = await login(app, platform_admin[0].email)
    r = await admin.post(f"/api/v1/admin/topups/{topup.id}/approve")
    assert r.status_code == 409 and r.json()["error"]["code"] == "paypal_auto"  # never approved by hand
    await admin.aclose()
    r = await c.post("/api/v1/billing/paypal/cancel", json={"order_id": oid})
    assert r.json()["status"] == "rejected"


async def test_checkout_unavailable_until_paypal_is_connected(buyer, usd_package):
    c, _ = buyer
    assert (await c.get("/api/v1/billing/summary")).json()["paypal_enabled"] is False
    r = await c.post("/api/v1/billing/paypal/orders", json={"package_id": str(usd_package.id)})
    assert r.status_code == 503 and r.json()["error"]["code"] == "payments_unavailable"
