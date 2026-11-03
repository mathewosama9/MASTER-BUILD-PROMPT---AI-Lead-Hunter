"""Platform admin: access control, settings, packages, top-up review, workspaces and contact requests."""

import asyncio
import base64
import uuid
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.models import ContactRequest, CreditPackage, CreditTransaction, TelegramAccount, Workspace
from app.models.enums import CreditKind, TelegramLinkStatus
from app.services import credits as credit_svc
from tests.conftest import deliver_all, login, make_user

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


@pytest.fixture
async def admin(app, db):
    user, ws = await make_user(db)
    user.is_superuser = True
    await db.commit()
    c = await login(app, user.email)
    yield c, user, ws
    await c.aclose()


@pytest.fixture
async def client_ws(app, db):
    user, ws = await make_user(db, billing_exempt=False)
    c = await login(app, user.email)
    yield c, user, ws
    await c.aclose()


@pytest.fixture
async def package(db):
    pkg = CreditPackage(name_ar="باقة", name_en="Pack 300", credits=300, price=Decimal("450"), currency="EGP")
    db.add(pkg)
    await db.commit()
    yield pkg
    await db.delete(pkg)
    await db.commit()


async def request_topup(c, pkg) -> dict:
    r = await c.post(
        "/api/v1/billing/topups",
        json={
            "package_id": str(pkg.id),
            "method": "vodafone_cash",
            "receipt_filename": "r.png",
            "receipt_base64": base64.b64encode(PNG).decode(),
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


ADMIN_GETS = ["/settings", "/packages", "/topups", "/workspaces", "/contacts"]


async def test_non_superusers_get_403_everywhere(client, client_ws):
    for c in (client, client_ws[0]):  # an owner of an exempt workspace, and a paying client
        for path in ADMIN_GETS:
            assert (await c.get(f"/api/v1/admin{path}")).status_code == 403, path
        assert (
            await c.put("/api/v1/admin/settings", json={"trial_days": 1, "trial_credits": 1, "credits_per_contact": 1})
        ).status_code == 403
        assert (await c.post(f"/api/v1/admin/topups/{uuid.uuid4()}/approve")).status_code == 403


async def test_anonymous_gets_401(app):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        assert (await c.get("/api/v1/admin/topups")).status_code == 401


async def test_me_exposes_superuser_flag(admin, client_ws):
    assert (await admin[0].get("/api/v1/auth/me")).json()["user"]["is_superuser"] is True
    assert (await client_ws[0].get("/api/v1/auth/me")).json()["user"]["is_superuser"] is False


async def test_settings_round_trip_and_validation(admin, db):
    c = admin[0]
    old = (await c.get("/api/v1/admin/settings")).json()
    try:
        body = {**old, "trial_days": 14, "trial_credits": 50, "payment_instructions_ar": "حوّل على 0100"}
        assert (await c.put("/api/v1/admin/settings", json=body)).status_code == 200
        assert (await c.get("/api/v1/public/trial")).json()["trial_credits"] == 50
        assert (await c.put("/api/v1/admin/settings", json={**old, "credits_per_contact": 0})).status_code == 422
    finally:
        await c.put("/api/v1/admin/settings", json=old)


async def test_packages_create_edit_deactivate(admin, anon_client):
    c = admin[0]
    r = await c.post(
        "/api/v1/admin/packages", json={"name_ar": "أ", "name_en": "Admin pack", "credits": 100, "price": "150.50"}
    )
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    assert (await c.patch(f"/api/v1/admin/packages/{pid}", json={"price": "175"})).json()["price"] == "175.00"
    public = [p["name_en"] for p in (await anon_client.get("/api/v1/public/packages")).json()]
    assert "Admin pack" in public
    assert (await c.patch(f"/api/v1/admin/packages/{pid}", json={"active": False})).json()["active"] is False
    public = [p["name_en"] for p in (await anon_client.get("/api/v1/public/packages")).json()]
    assert "Admin pack" not in public
    assert any(p["id"] == pid for p in (await c.get("/api/v1/admin/packages")).json())  # kept, not deleted


@pytest.fixture
async def anon_client(app):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        yield c


async def test_approve_topup_grants_credits_once(admin, client_ws, package, db):
    a, cu, cw = admin[0], client_ws[0], client_ws[2]
    w = await db.get(Workspace, cw.id)
    w.trial_ends_at = w.created_at  # an expired trial: buying ends the trial restriction
    await db.commit()
    t = await request_topup(cu, package)
    pending = (await a.get("/api/v1/admin/topups", params={"status": "pending"})).json()
    row = next(x for x in pending if x["id"] == t["id"])
    assert row["workspace_name"] == cw.name and row["requested_by"]
    rec = await a.get(f"/api/v1/admin/topups/{t['id']}/receipt")
    assert rec.status_code == 200 and rec.content == PNG

    r = await a.post(f"/api/v1/admin/topups/{t['id']}/approve")
    assert r.status_code == 200 and r.json()["status"] == "approved"
    again = await a.post(f"/api/v1/admin/topups/{t['id']}/approve")
    assert again.status_code == 409 and again.json()["error"]["code"] == "already_reviewed"

    summary = (await cu.get("/api/v1/billing/summary")).json()
    assert summary["balance"] == 300 and summary["on_trial"] is False and not summary["trial_expired"]
    ledger = (await cu.get("/api/v1/billing/transactions")).json()["items"]
    assert ledger[0]["kind"] == "purchase" and ledger[0]["delta"] == 300 and "450" in ledger[0]["note"]
    mine = (await cu.get("/api/v1/billing/topups")).json()
    assert mine[0]["status"] == "approved"


async def test_concurrent_approvals_grant_once(app, admin, client_ws, package, db):
    from tests.conftest import login as login_

    t = await request_topup(client_ws[0], package)
    second = await login_(app, admin[1].email)
    try:
        results = await asyncio.gather(
            admin[0].post(f"/api/v1/admin/topups/{t['id']}/approve"),
            second.post(f"/api/v1/admin/topups/{t['id']}/approve"),
        )
    finally:
        await second.aclose()
    assert sorted(r.status_code for r in results) == [200, 409]
    purchases = (
        await db.scalars(
            select(CreditTransaction).where(
                CreditTransaction.workspace_id == client_ws[2].id, CreditTransaction.kind == CreditKind.PURCHASE
            )
        )
    ).all()
    assert len(purchases) == 1


async def test_reject_topup_needs_a_reason_and_grants_nothing(admin, client_ws, package):
    a, cu = admin[0], client_ws[0]
    t = await request_topup(cu, package)
    assert (await a.post(f"/api/v1/admin/topups/{t['id']}/reject", json={"reason": ""})).status_code == 422
    r = await a.post(f"/api/v1/admin/topups/{t['id']}/reject", json={"reason": "Amount does not match the package"})
    assert r.status_code == 200 and r.json()["status"] == "rejected"
    assert (await a.post(f"/api/v1/admin/topups/{t['id']}/approve")).status_code == 409
    mine = (await cu.get("/api/v1/billing/topups")).json()[0]
    assert mine["status"] == "rejected" and mine["reason"] == "Amount does not match the package"
    assert (await cu.get("/api/v1/billing/summary")).json()["balance"] == 0


async def test_new_topup_notifies_platform_admins(admin, client_ws, package, db, monkeypatch):
    sent: list[dict] = []

    async def fake_send(token, method, payload):
        sent.append(payload)
        return {"message_id": 1}

    monkeypatch.setattr("app.services.notifications._send", fake_send)
    monkeypatch.setattr(get_settings(), "telegram_bot_token", "tok")
    db.add(
        TelegramAccount(
            user_id=admin[1].id,
            workspace_id=admin[2].id,
            telegram_user_id=int(uuid.uuid4().int % 10**9),
            chat_id=777,
            status=TelegramLinkStatus.APPROVED,
        )
    )
    await db.commit()
    await request_topup(client_ws[0], package)
    await deliver_all()
    texts = [p["text"] for p in sent if p["chat_id"] == 777]
    assert texts and "Pack 300" in texts[0] and client_ws[2].name in texts[0]


async def test_workspace_list_adjust_and_suspend(app, admin, client_ws, db):
    a, cu, cw = admin[0], client_ws[0], client_ws[2]
    page = (await a.get("/api/v1/admin/workspaces", params={"q": client_ws[1].email})).json()
    assert page["total"] == 1 and page["items"][0]["id"] == str(cw.id)
    assert page["items"][0]["owner_email"] == client_ws[1].email

    assert (
        await a.post(f"/api/v1/admin/workspaces/{cw.id}/adjust", json={"delta": 25, "note": "goodwill"})
    ).status_code == 200
    r = await a.post(f"/api/v1/admin/workspaces/{cw.id}/adjust", json={"delta": -100, "note": "oops"})
    assert r.status_code == 409
    assert (await a.post(f"/api/v1/admin/workspaces/{cw.id}/adjust", json={"delta": 5, "note": ""})).status_code == 422
    assert (await cu.get("/api/v1/billing/summary")).json()["balance"] == 25
    tx = (await cu.get("/api/v1/billing/transactions")).json()["items"][0]
    assert tx["kind"] == "manual_adjust" and tx["note"] == "goodwill"

    # Suspension locks the client out; the admin can't lock themselves out.
    assert (await a.patch(f"/api/v1/admin/workspaces/{cw.id}", json={"suspended": True})).status_code == 200
    me = await cu.get("/api/v1/auth/me")
    assert me.status_code == 403 and me.json()["error"]["code"] == "workspace_suspended"
    assert (await a.patch(f"/api/v1/admin/workspaces/{admin[2].id}", json={"suspended": True})).status_code == 409
    w = await db.get(Workspace, cw.id)
    await db.refresh(w)
    with pytest.raises(credit_svc.AppError):
        await credit_svc.ensure_can_spend(db, w)
    assert (await a.patch(f"/api/v1/admin/workspaces/{cw.id}", json={"suspended": False})).status_code == 200
    assert (await cu.get("/api/v1/auth/me")).status_code == 200


async def test_contact_requests_are_listed_and_handled(admin, anon_client, db):
    email = f"c-{uuid.uuid4().hex[:6]}@x.sa"
    assert (await anon_client.post("/api/v1/public/contact", json={"name": "Huda", "email": email})).status_code == 201
    a = admin[0]
    row = next(
        x for x in (await a.get("/api/v1/admin/contacts", params={"status": "new"})).json() if x["email"] == email
    )
    r = await a.post(f"/api/v1/admin/contacts/{row['id']}/handled")
    assert r.status_code == 200 and r.json()["status"] == "handled"
    assert email not in [x["email"] for x in (await a.get("/api/v1/admin/contacts", params={"status": "new"})).json()]
    stored = await db.scalar(select(ContactRequest).where(ContactRequest.email == email))
    await db.refresh(stored)
    assert stored.handled_at is not None
