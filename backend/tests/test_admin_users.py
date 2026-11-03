"""Platform admin control over one user: editing, devices and last seen, granting packages (api/v1/admin_users.py)."""

import uuid
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import select

from app.models import CreditPackage, CreditTransaction, TopUpRequest, Workspace
from app.models.enums import CreditKind
from app.services import presence
from tests.conftest import PASSWORD, login, make_user


@pytest.fixture
async def admin(app, platform_admin):
    c = await login(app, platform_admin[0].email)
    yield c
    await c.aclose()


def grant(ws, pkg) -> dict:
    return {"workspace_id": str(ws.id), "package_id": str(pkg.id), "request_id": str(uuid.uuid4())}


@pytest.fixture
async def customer(db):
    return await make_user(db, billing_exempt=False)


async def test_detail_shows_devices_and_last_seen(app, admin, customer):
    presence._seen.clear()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, client=("41.33.7.7", 1)),
        base_url="http://test",
        headers={"user-agent": "Mozilla/5.0 (Windows NT 10.0) Chrome/130.0"},
    ) as c:
        r = await c.post("/api/v1/auth/login", json={"email": customer[0].email, "password": PASSWORD})
        assert r.status_code == 200
    d = (await admin.get(f"/api/v1/admin/users/{customer[0].id}")).json()
    assert d["last_seen_at"] and d["last_seen_ip"] == "41.33.7.7"
    [device] = d["devices"]
    assert "Chrome/130" in device["user_agent"] and device["ip"] == "41.33.7.7" and device["shared_with"] == 0
    assert d["suspicion"] == "none"
    row = (await admin.get("/api/v1/admin/users", params={"q": customer[0].email})).json()["items"][0]
    assert row["last_seen_at"]


async def test_admin_edits_user_fields_and_notes(admin, db, customer, owner):
    uid = customer[0].id
    r = await admin.patch(
        f"/api/v1/admin/users/{uid}",
        json={"full_name": "Renamed", "nationality": "sa", "phone": "+966 50 000 1111", "admin_notes": "VIP"},
    )
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["full_name"] == "Renamed" and d["nationality"] == "SA" and d["admin_notes"] == "VIP"

    taken = await admin.patch(f"/api/v1/admin/users/{uid}", json={"email": owner[0].email})
    assert taken.status_code == 409 and taken.json()["error"]["code"] == "email_taken"
    new_email = f"new-{uuid.uuid4().hex[:6]}@example.com"
    d = (await admin.patch(f"/api/v1/admin/users/{uid}", json={"email": new_email})).json()
    assert d["email"] == new_email and d["email_verified_at"] is None
    d = (await admin.patch(f"/api/v1/admin/users/{uid}", json={"email_verified": True, "is_active": False})).json()
    assert d["email_verified_at"] and d["is_active"] is False
    assert (await admin.patch(f"/api/v1/admin/users/{uid}", json={"nationality": "XX"})).status_code == 400


async def test_admin_cannot_deactivate_a_platform_admin(admin, platform_admin):
    r = await admin.patch(f"/api/v1/admin/users/{platform_admin[0].id}", json={"is_active": False})
    assert r.status_code == 409


async def test_grant_package_records_payment_and_credits(admin, db, customer):
    pkg = CreditPackage(name_ar="باقة", name_en="Pack", credits=300, price=Decimal("49.00"), currency="USD")
    db.add(pkg)
    await db.commit()
    user, ws = customer
    r = await admin.post(
        f"/api/v1/admin/users/{user.id}/grant-package",
        json={**grant(ws, pkg), "method": "cash", "reference": "R-1"},
    )
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["workspace"]["balance"] == 300
    [topup] = d["topups"]
    assert topup["status"] == "approved" and topup["method"] == "cash" and Decimal(topup["amount"]) == 49
    assert d["workspaces"][0]["paid"] == {"USD": "49.00"}

    gift = await admin.post(
        f"/api/v1/admin/users/{user.id}/grant-package",
        json={**grant(ws, pkg), "amount": 0},
    )
    assert gift.json()["topups"][0]["method"] == "complimentary"
    await db.refresh(ws)
    assert ws.credit_balance == 600
    kinds = (await db.scalars(select(CreditTransaction.kind).where(CreditTransaction.workspace_id == ws.id))).all()
    assert kinds.count(CreditKind.PURCHASE) == 2
    assert len((await db.scalars(select(TopUpRequest).where(TopUpRequest.workspace_id == ws.id))).all()) == 2

    other_ws = Workspace(name="Other", slug=f"o-{uuid.uuid4().hex[:8]}", settings={})
    db.add(other_ws)
    await db.commit()
    r = await admin.post(
        f"/api/v1/admin/users/{user.id}/grant-package",
        json=grant(other_ws, pkg),
    )
    assert r.status_code == 404  # only a workspace the user belongs to


async def test_clients_cannot_use_admin_payment_methods(app, db, customer):
    pkg = CreditPackage(name_ar="ب", name_en="P", credits=10, price=Decimal("5.00"), currency="USD")
    db.add(pkg)
    await db.commit()
    c = await login(app, customer[0].email)
    try:
        r = await c.post(
            "/api/v1/billing/topups",
            json={
                "package_id": str(pkg.id),
                "method": "complimentary",
                "receipt_filename": "r.pdf",
                "receipt_base64": "JVBERi0xLjQ=",
            },
        )
        assert r.status_code == 422
    finally:
        await c.aclose()


async def test_password_reset_link_is_emailed(admin, customer, outbox):
    r = await admin.post(f"/api/v1/admin/users/{customer[0].id}/password-reset")
    assert r.status_code == 202
    assert [m["to"] for m in outbox] == [customer[0].email]


async def test_editing_is_superuser_only(client, customer):
    assert (await client.patch(f"/api/v1/admin/users/{customer[0].id}", json={"full_name": "x"})).status_code == 403


async def test_grant_package_is_idempotent_per_request(admin, db, customer):
    pkg = CreditPackage(name_ar="ب", name_en="Once", credits=50, price=Decimal("9.00"), currency="USD")
    db.add(pkg)
    await db.commit()
    user, ws = customer
    body = {"workspace_id": str(ws.id), "package_id": str(pkg.id), "request_id": str(uuid.uuid4())}
    for _ in range(2):  # a double click or a retried request
        assert (await admin.post(f"/api/v1/admin/users/{user.id}/grant-package", json=body)).status_code == 200
    await db.refresh(ws)
    assert ws.credit_balance == 50
    assert len((await db.scalars(select(TopUpRequest).where(TopUpRequest.workspace_id == ws.id))).all()) == 1


async def test_admin_phone_edit_is_validated(admin, customer):
    r = await admin.patch(f"/api/v1/admin/users/{customer[0].id}", json={"phone": "call me"})
    assert r.status_code == 422


async def test_presence_writes_at_most_once_per_window(app, db, customer):
    from app.core.redis import async_redis
    from app.models import User

    uid = customer[0].id
    presence._seen.clear()
    r = async_redis()
    await r.delete(f"presence:{uid}")
    await r.aclose()
    c = await login(app, customer[0].email)
    try:
        await c.get("/api/v1/auth/me")
        await presence.drain()
        first = await db.scalar(select(User.last_seen_at).where(User.id == uid))
        presence._seen.clear()  # as if another process: Redis still says "written recently"
        await c.get("/api/v1/auth/me")
        await presence.drain()
        await db.rollback()  # fresh snapshot
        assert first is not None
        assert await db.scalar(select(User.last_seen_at).where(User.id == uid)) == first
    finally:
        await c.aclose()


async def test_money_and_identity_actions_are_dashboard_only(app, db, platform_admin, customer):
    """The bot's service token may review signups, but not grant credits, edit identity or send password resets."""
    import random

    from app.models import TelegramAccount
    from app.models.enums import TelegramLinkStatus

    tg = random.randint(10_000_000, 99_999_999)
    db.add(
        TelegramAccount(
            user_id=platform_admin[0].id,
            workspace_id=platform_admin[1].id,
            telegram_user_id=tg,
            chat_id=tg,
            status=TelegramLinkStatus.APPROVED,
        )
    )
    await db.commit()
    headers = {"x-service-token": "test-service-token", "x-telegram-user-id": str(tg)}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t", headers=headers) as bot:
        uid = customer[0].id
        assert (await bot.get(f"/api/v1/admin/users/{uid}")).status_code == 200
        for method, path, body in (
            ("PATCH", f"/api/v1/admin/users/{uid}", {"email": "taken-over@example.com"}),
            ("POST", f"/api/v1/admin/users/{uid}/password-reset", None),
            ("POST", f"/api/v1/admin/users/{uid}/grant-package", grant(customer[1], customer[1])),
        ):
            r = await bot.request(method, path, json=body)
            assert r.status_code == 403 and r.json()["error"]["code"] == "dashboard_only", (path, r.text)


async def test_search_treats_wildcards_literally(admin, db, customer):
    customer[0].full_name = "100% Real"
    await db.commit()
    hits = (await admin.get("/api/v1/admin/users", params={"q": "100%", "page_size": 100})).json()["items"]
    assert [u["id"] for u in hits] == [str(customer[0].id)]
    none = (await admin.get("/api/v1/admin/users", params={"q": "_%_", "page_size": 100})).json()
    assert none["total"] == 0


async def test_login_is_limited_per_email(app, customer, monkeypatch):
    from app.core.config import get_settings
    from app.core.redis import async_redis
    from app.core.security import password_fingerprint

    monkeypatch.setattr(get_settings(), "login_limit_per_email", 2)
    r = async_redis()
    await r.delete(f"ratelimit:login:{password_fingerprint(customer[0].email)}")
    await r.aclose()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        for _ in range(2):
            bad = await c.post("/api/v1/auth/login", json={"email": customer[0].email, "password": "wrong"})
            assert bad.status_code == 401
        r = await c.post("/api/v1/auth/login", json={"email": customer[0].email.upper(), "password": PASSWORD})
        assert r.status_code == 429

