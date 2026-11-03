"""Public site endpoints: packages, the contact form, and Telegram notifications to platform admins."""

import uuid
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.core.redis import async_redis
from app.models import ContactRequest, CreditPackage, TelegramAccount, User
from app.models.enums import TelegramLinkStatus
from app.services.notifications import notify_platform_admins
from tests.conftest import deliver_all, make_user


@pytest.fixture(autouse=True)
async def _fresh_limits():
    async def clear():
        r = async_redis()
        keys = [k async for k in r.scan_iter("ratelimit:contact:*")]
        if keys:
            await r.delete(*keys)
        await r.aclose()

    await clear()
    yield
    await clear()


@pytest.fixture
async def anon(app):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture
def sent(monkeypatch):
    """Capture Telegram Bot API calls."""
    calls: list[tuple[str, dict]] = []

    async def fake_send(token, method, payload):
        calls.append((token, payload))
        return {"message_id": len(calls)}

    monkeypatch.setattr("app.services.notifications._send", fake_send)
    monkeypatch.setattr(get_settings(), "telegram_bot_token", "bot-token")
    return calls


async def link_admin(db, *, superuser: bool = True) -> User:
    user, ws = await make_user(db)
    user.is_superuser = superuser
    db.add(
        TelegramAccount(
            user_id=user.id,
            workspace_id=ws.id,
            telegram_user_id=int(uuid.uuid4().int % 10**9),
            chat_id=int(uuid.uuid4().int % 10**9),
            status=TelegramLinkStatus.APPROVED,
        )
    )
    await db.commit()
    return user


async def test_public_packages_lists_active_only(anon, db):
    on = CreditPackage(name_ar="أساسية", name_en="Starter", credits=200, price=Decimal("300"), sort=1)
    off = CreditPackage(name_ar="مخفية", name_en="Hidden", credits=1, price=Decimal("1"), active=False)
    db.add_all([on, off])
    await db.commit()
    try:
        names = [p["name_en"] for p in (await anon.get("/api/v1/public/packages")).json()]
        assert "Starter" in names and "Hidden" not in names
    finally:
        await db.delete(on)
        await db.delete(off)
        await db.commit()


async def test_contact_request_is_saved_and_admins_notified(anon, db, sent):
    await link_admin(db)
    await link_admin(db, superuser=False)  # ordinary users are never notified
    email = f"lead-{uuid.uuid4().hex[:6]}@clinic.sa"
    body = {
        "name": "Omar",
        "company": "Smile Clinic",
        "email": email,
        "phone": "+966 50 000 0000",
        "interest": "whatsapp_bot",
        "message": "We miss WhatsApp messages at night.",
        "locale": "ar",
    }
    r = await anon.post("/api/v1/public/contact", json=body)
    assert r.status_code == 201 and r.json() == {"status": "received"}
    row = await db.scalar(select(ContactRequest).where(ContactRequest.email == email))
    assert row and row.interest == "whatsapp_bot" and row.status == "new" and row.company == "Smile Clinic"
    await deliver_all()
    texts = [p["text"] for _, p in sent]
    assert any("Smile Clinic" in t and email in t and "whatsapp_bot" in t for t in texts)
    assert all(tok == "bot-token" for tok, _ in sent)


async def test_contact_honeypot_and_validation(anon, db, sent):
    email = f"bot-{uuid.uuid4().hex[:6]}@spam.io"
    r = await anon.post("/api/v1/public/contact", json={"name": "Bot", "email": email, "website": "http://spam"})
    assert r.status_code == 201
    assert await db.scalar(select(ContactRequest).where(ContactRequest.email == email)) is None
    assert sent == []
    for bad in (
        {"name": "A", "email": "a@b.co"},
        {"name": "Ali", "email": "nope"},
        {"name": "Ali", "email": "a@b.co", "interest": "x"},
    ):
        assert (await anon.post("/api/v1/public/contact", json=bad)).status_code == 422


async def test_contact_is_rate_limited(anon, monkeypatch):
    monkeypatch.setattr(get_settings(), "contact_limit_per_hour", 1)
    body = {"name": "Ali", "email": "ali@example.com"}
    assert (await anon.post("/api/v1/public/contact", json=body)).status_code == 201
    assert (await anon.post("/api/v1/public/contact", json=body)).status_code == 429


async def test_admin_notification_needs_a_bot_token(db, sent, monkeypatch):
    await link_admin(db)
    monkeypatch.setattr(get_settings(), "telegram_bot_token", None)  # and no Telegram integration in the workspace
    assert await notify_platform_admins(db, "hello") == 0
    assert sent == []


# ---- live preview: real results from the showcase workspace only ----


async def _seed_search(db, ws, *, industry="cafes", city="Dubai", names=("Café Mocha House", "Bean Bar", "Quiet")):
    from datetime import UTC, datetime

    from app.models import Business, BusinessContact, Campaign, CampaignLead, LeadAssessment

    c = Campaign(
        workspace_id=ws.id, name="s", status="completed", country="AE", city=city, industry=industry,
        completed_at=datetime.now(UTC),
    )
    db.add(c)
    await db.flush()
    for i, name in enumerate(names):
        b = Business(
            workspace_id=ws.id, name=name, normalized_name=name.lower(), city=city, country="AE", industry=industry,
            latest_score=90 - i * 10, contact_count=0 if name == "Quiet" else 1,
        )
        db.add(b)
        await db.flush()
        db.add(CampaignLead(campaign_id=c.id, business_id=b.id, discovered_via="osm"))
        if name != "Quiet":
            db.add(BusinessContact(business_id=b.id, type="whatsapp", value="+971500000000",
                                   normalized_value=f"+97150000000{i}", source_provider="osm"))
            db.add(LeadAssessment(business_id=b.id, provider="heuristic",
                                  potential_problems=["No online booking. Replies slowly."], opportunity="Sell them o_bot"))
    await db.commit()


@pytest.fixture
async def showcase(db):
    from app.services import credits as credit_svc

    _, ws = await make_user(db)
    s = await credit_svc.platform_settings(db)
    s.showcase_workspace_id = ws.id
    await db.commit()
    yield ws
    s = await credit_svc.platform_settings(db)
    s.showcase_workspace_id = None
    await db.commit()


def test_mask_name_hides_all_but_the_start():
    from app.api.v1.public import mask_name

    assert mask_name("مقهى موكا هاوس") == "مقهى •••• ••••"
    assert mask_name("Starbucks") == "St••••••"


async def test_preview_is_empty_without_a_showcase(anon):
    assert (await anon.get("/api/v1/public/preview/options")).json() == {"categories": []}
    r = await anon.get("/api/v1/public/preview", params={"category": "marketing_agency", "country": "AE"})
    assert r.json()["count"] == 0


async def test_preview_shows_masked_real_results_from_the_showcase_only(anon, db, showcase):
    await _seed_search(db, showcase)
    _, customer = await make_user(db)
    await _seed_search(db, customer, names=("Customer Secret Café", "Other"))  # must never appear

    opts = (await anon.get("/api/v1/public/preview/options")).json()["categories"]
    agency = next(c for c in opts if c["key"] == "marketing_agency")
    assert agency["places"] == [{"country": "AE", "city": "Dubai", "count": 2}]

    r = await anon.get("/api/v1/public/preview", params={"category": "marketing_agency", "country": "AE", "city": "Dubai"})
    data = r.json()
    assert data["count"] == 2 and data["searched_at"]  # the business without a contact isn't counted
    assert [s["name"] for s in data["samples"]] == ["Café ••••• •••••", "Bean •••"]
    first = data["samples"][0]
    assert first["score"] == 90 and first["contact_types"] == ["whatsapp"]
    assert first["reason"] == "No online booking." and "o_bot" not in str(data)
    assert "+9715" not in r.text and "Secret" not in r.text

    other = await anon.get("/api/v1/public/preview", params={"category": "marketing_agency", "country": "AE", "city": "Abu Dhabi"})
    assert other.json()["count"] == 0


async def test_admin_marks_the_showcase_workspace(app, db, platform_admin):
    from tests.conftest import login

    _, ws = await make_user(db)
    c = await login(app, platform_admin[0].email)
    try:
        assert (await c.patch(f"/api/v1/admin/workspaces/{ws.id}", json={"showcase": True})).status_code == 200
        rows = (await c.get("/api/v1/admin/workspaces", params={"page_size": 100})).json()["items"]
        assert [r["id"] for r in rows if r["is_showcase"]] == [str(ws.id)]
        await c.patch(f"/api/v1/admin/workspaces/{ws.id}", json={"showcase": False})
        rows = (await c.get("/api/v1/admin/workspaces", params={"page_size": 100})).json()["items"]
        assert not any(r["is_showcase"] for r in rows)
    finally:
        await c.aclose()
