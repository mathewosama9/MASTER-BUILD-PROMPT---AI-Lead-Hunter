"""Admin review of self-signups and duplicate-account detection (services/signup_review.py, api/v1/admin_users.py)."""

import random
import uuid

import httpx
import pytest
from sqlalchemy import select

from app.core.redis import async_redis
from app.models import Notification, TelegramAccount, User, Workspace
from app.models.enums import TelegramLinkStatus
from app.services import credits as credit_svc
from app.services import signup_review as review
from app.services.notify import templates
from tests.conftest import link_token, login

SVC = {"x-service-token": "test-service-token"}


@pytest.fixture(autouse=True)
async def _fresh_signup_limit():
    r = async_redis()
    keys = [k async for k in r.scan_iter("ratelimit:signup:*")]
    if keys:
        await r.delete(*keys)
    await r.aclose()


def client_for(app, ip: str = "127.0.0.1") -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=(ip, 5000)), base_url="http://test")


def phone() -> str:
    return "+2010" + "".join(random.choices("0123456789", k=8))


def body(**over) -> dict:
    return {
        "full_name": "Mona Adel",
        "company": "Cairo Smiles",
        "email": f"mona-{uuid.uuid4().hex[:8]}@example.com",
        "phone": phone(),
        "password": "a-long-enough-password",
        "nationality": "EG",
        "locale": "ar",
        **over,
    }


async def register(c: httpx.AsyncClient, data: dict) -> dict:
    r = await c.post("/api/v1/auth/register", json=data)
    assert r.status_code == 201, r.text
    c.headers["x-csrf-token"] = r.json()["csrf_token"]
    return r.json()


async def admin_notes(db, admin: User, kind: str) -> list[Notification]:
    q = select(Notification).where(Notification.user_id == admin.id, Notification.kind == kind)
    return list((await db.scalars(q)).all())


def test_canonical_email_and_phone():
    assert review.canonical_email("M.Ona.Adel+promo@GoogleMail.com") == "monaadel@gmail.com"
    assert review.canonical_email("sara+x@company.com") == "sara@company.com"
    assert review.canonical_email("s.ara@company.com") == "s.ara@company.com"  # dots matter outside Gmail
    assert review.canonical_phone("+20 100 123 4567") == review.canonical_phone("01001234567")
    assert review.canonical_phone("123") is None
    assert review.public_ip("10.0.0.5") is None and review.public_ip("41.33.1.2") == "41.33.1.2"


async def test_signup_waits_for_approval_then_trial_starts(app, db, outbox, platform_admin):
    admin = platform_admin[0]
    async with client_for(app) as c:
        me = await register(c, body())
        assert me["user"]["approval_status"] == "pending"
        uid = me["user"]["id"]
        ws = await db.get(Workspace, uuid.UUID(me["workspace_id"]))

        # Confirming the email alone does not start the trial while the account waits for review.
        [mail] = [m for m in outbox if m["to"] == me["user"]["email"]]
        assert (await c.post("/api/v1/auth/email/verify", json={"token": link_token(mail)})).status_code == 200
        await db.refresh(ws)
        assert ws.credit_balance == 0 and ws.trial_ends_at is None
        summary = (await c.get("/api/v1/billing/summary")).json()
        assert summary["awaiting_approval"] and not summary["awaiting_verification"]
        r = await c.post(
            "/api/v1/campaigns",
            json={
                "name": "First",
                "country": "EG",
                "industry": "dental_clinics",
                "sources": [{"provider_key": "manual", "manual_urls": ["https://example-clinic.eg"]}],
                "start": True,
            },
        )
        assert r.status_code == 403 and r.json()["error"]["code"] == "account_pending"

        # The admin got a review notification (with Approve / Reject buttons on Telegram).
        [note] = [n for n in await admin_notes(db, admin, "admin_signup_review") if n.params["user_id"] == uid]
        buttons = templates.telegram_buttons(note.kind, "ar", note.params)
        assert buttons["inline_keyboard"][0][0]["callback_data"] == f"adm:ok:{uid}"

        a = await login(app, admin.email)
        try:
            row = (await a.get("/api/v1/admin/users", params={"status": "pending", "q": me["user"]["email"]})).json()
            assert [u["id"] for u in row["items"]] == [uid]
            assert row["items"][0]["nationality"] == "EG" and row["items"][0]["workspace"]["name"] == "Cairo Smiles"
            r = await a.post(f"/api/v1/admin/users/{uid}/approve")
            assert r.status_code == 200, r.text
            assert r.json()["approval_status"] == "approved" and r.json()["reviewed_by"] == admin.email
            again = await a.post(f"/api/v1/admin/users/{uid}/approve")
            assert again.status_code == 409 and again.json()["error"]["code"] == "already_reviewed"
        finally:
            await a.aclose()
        await db.refresh(ws)
        assert ws.credit_balance == 100 and await credit_svc.on_trial(db, ws)  # once, not twice
        assert not (await c.get("/api/v1/billing/summary")).json()["awaiting_approval"]


async def test_second_account_from_same_device_is_flagged_with_reasons(app, db, outbox, platform_admin):
    admin = platform_admin[0]
    shared_phone = phone()
    fp = "ab" * 16
    async with client_for(app, "41.33.10.20") as c:  # one browser: the device cookie carries over
        gmail = f"m.ona.{uuid.uuid4().hex[:6]}@gmail.com"
        first = await register(c, body(phone=shared_phone, device_fp=fp, email=gmail))
        await c.post("/api/v1/auth/logout")
        alias = first["user"]["email"].replace(".", "", 1).replace("@", "+trial@")  # same Gmail inbox
        second = await register(c, body(phone=shared_phone.replace("+20", "0"), device_fp=fp, email=alias))

    sid = second["user"]["id"]
    [note] = [n for n in await admin_notes(db, admin, "admin_signup_suspicious") if n.params["user_id"] == sid]
    assert note.params["matches"] == 1 and first["user"]["email"] in note.params["reasons_ar"]
    assert "نفس رقم الموبايل" in note.body or "same phone" in note.body

    a = await login(app, admin.email)
    try:
        flagged = (await a.get("/api/v1/admin/users", params={"suspicious": True, "page_size": 100})).json()
        ids = {u["id"] for u in flagged["items"]}
        assert {first["user"]["id"], sid} <= ids
        detail = (await a.get(f"/api/v1/admin/users/{sid}")).json()
        [dup] = detail["duplicates"]
        assert dup["user_id"] == first["user"]["id"] and dup["strong"]
        assert set(dup["kinds"]) == {"device", "fingerprint", "phone", "email", "ip"}
        assert detail["signup_ip"] == "41.33.10.20" and detail["logins"][0]["action"] == "auth.registered"
        assert (await a.get("/api/v1/admin/users/summary")).json()["suspicious_pending"] >= 2

        # Reject the duplicate: it can no longer sign in, and its open session stops working.
        r = await a.post(f"/api/v1/admin/users/{sid}/reject", json={"reason": "Second account"})
        assert r.status_code == 200 and r.json()["approval_status"] == "rejected"
    finally:
        await a.aclose()
    user = await db.get(User, uuid.UUID(sid))
    await db.refresh(user)
    assert user.review_note == "Second account"
    async with client_for(app) as c:
        r = await c.post("/api/v1/auth/login", json={"email": alias, "password": "a-long-enough-password"})
        assert r.status_code == 403 and r.json()["error"]["code"] == "account_rejected"
    [note] = await admin_notes(db, user, "account_rejected")  # emailed through the notification outbox
    assert "Second account" in note.body


async def test_unrelated_signups_are_not_flagged(app, db, platform_admin):
    async with client_for(app) as c1, client_for(app) as c2:
        a = await register(c1, body(device_fp="cd" * 16))
        b = await register(c2, body(device_fp="ef" * 16))
    assert await review.matches(db, uuid.UUID(a["user"]["id"])) == []
    assert await review.matches(db, uuid.UUID(b["user"]["id"])) == []


async def test_review_off_approves_clean_signups_but_holds_duplicates(app, db, outbox):
    s = await credit_svc.platform_settings(db)
    s.signup_review = False
    await db.commit()
    try:
        shared = phone()
        async with client_for(app) as c1, client_for(app) as c2:
            clean = await register(c1, body(phone=shared))
            dup = await register(c2, body(phone=shared))
        assert clean["user"]["approval_status"] == "approved"
        assert dup["user"]["approval_status"] == "pending"
    finally:
        s.signup_review = True
        await db.commit()


async def test_admin_users_api_is_superuser_only(client):
    assert (await client.get("/api/v1/admin/users")).status_code == 403
    assert (await client.get("/api/v1/admin/users/summary")).status_code == 403
    assert (await client.post(f"/api/v1/admin/users/{uuid.uuid4()}/approve")).status_code == 403


async def test_admin_cannot_reject_a_platform_admin(app, platform_admin):
    a = await login(app, platform_admin[0].email)
    try:
        r = await a.post(f"/api/v1/admin/users/{platform_admin[0].id}/reject", json={"reason": "nope"})
        assert r.status_code == 409 and r.json()["error"]["code"] == "cannot_reject_admin"
    finally:
        await a.aclose()


async def test_admin_approves_from_telegram(app, db, platform_admin):
    admin = platform_admin[0]
    tg_id = random.randint(10_000_000, 99_999_999)
    db.add(
        TelegramAccount(
            user_id=admin.id,
            workspace_id=platform_admin[1].id,
            telegram_user_id=tg_id,
            chat_id=tg_id,
            status=TelegramLinkStatus.APPROVED,
        )
    )
    await db.commit()
    async with client_for(app) as c:
        me = await register(c, body())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://t", headers={**SVC, "x-telegram-user-id": str(tg_id)}
    ) as bot:
        assert (await bot.get("/api/v1/telegram/whoami")).json()["is_superuser"] is True
        pending = (await bot.get("/api/v1/admin/users", params={"status": "pending", "page_size": 100})).json()
        assert me["user"]["id"] in {u["id"] for u in pending["items"]}
        r = await bot.post(f"/api/v1/admin/users/{me['user']['id']}/approve")
        assert r.status_code == 200 and r.json()["approval_status"] == "approved"
    user = await db.get(User, uuid.UUID(me["user"]["id"]))
    await db.refresh(user)
    assert user.reviewed_by == admin.id


async def test_existing_members_are_approved(app, owner):
    c = await login(app, owner[0].email)  # created by an admin, never reviewed
    try:
        assert (await c.get("/api/v1/auth/me")).json()["user"]["approval_status"] == "approved"
    finally:
        await c.aclose()
