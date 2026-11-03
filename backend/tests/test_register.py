"""Self-signup: a new workspace + owner, the free trial (after email confirmation) and abuse limits."""

import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select

from app.core.redis import async_redis
from app.models import CreditTransaction, User, Workspace
from app.models.enums import CreditKind
from app.services import credits as credit_svc
from tests.conftest import approve_signup, link_token


@pytest.fixture(autouse=True)
async def _fresh_signup_limit():
    async def clear():
        r = async_redis()
        keys = [k async for k in r.scan_iter("ratelimit:signup:*")]
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


def signup(**over) -> dict:
    return {
        "full_name": "Sara Ahmed",
        "company": "Nile Dental Clinics",
        "email": f"sara-{uuid.uuid4().hex[:8]}@example.com",
        "phone": "+20 100 123 4567",
        "password": "a-long-enough-password",
        "nationality": "EG",
        **over,
    }


async def test_signup_creates_owner_workspace_with_trial(anon, db, outbox):
    body = signup(locale="ar")
    r = await anon.post("/api/v1/auth/register", json=body)
    assert r.status_code == 201, r.text
    me = r.json()
    assert me["role"] == "owner" and me["workspace_name"] == "Nile Dental Clinics"
    assert me["user"]["email"] == body["email"] and me["user"]["locale"] == "ar"

    # Signed in straight away (session cookie + CSRF token).
    anon.headers["x-csrf-token"] = me["csrf_token"]
    assert (await anon.get("/api/v1/auth/me")).json()["workspace_id"] == me["workspace_id"]

    assert me["user"]["email_verified_at"] is None
    ws = await db.get(Workspace, uuid.UUID(me["workspace_id"]))
    await db.refresh(ws)
    # No trial credits until the email is confirmed; campaigns can't start yet.
    assert ws.credit_balance == 0 and ws.trial_ends_at is None and not ws.billing_exempt
    summary = (await anon.get("/api/v1/billing/summary")).json()
    assert summary["awaiting_verification"] and not summary["on_trial"]
    campaign = {
        "name": "First",
        "country": "EG",
        "industry": "dental_clinics",
        "sources": [{"provider_key": "manual", "manual_urls": ["https://example-clinic.eg"]}],
        "start": True,
    }
    r = await anon.post("/api/v1/campaigns", json=campaign)
    assert r.status_code == 403 and r.json()["error"]["code"] == "email_unverified"

    # The signup waits for the platform admin; once approved, the confirmation email (in the user's language)
    # carries the link that starts the trial.
    assert me["user"]["approval_status"] == "pending" and me["user"]["nationality"] == "EG"
    await approve_signup(body["email"])
    [mail] = [m for m in outbox if m["to"] == body["email"]]
    assert "أكّد" in mail["subject"] and "/verify-email?token=" in mail["text"]
    assert (await anon.post("/api/v1/auth/email/verify", json={"token": link_token(mail)})).status_code == 200
    await db.refresh(ws)
    assert ws.credit_balance == 100 and not (await anon.get("/api/v1/billing/summary")).json()["awaiting_verification"]
    assert abs(ws.trial_ends_at - (datetime.now(UTC) + timedelta(days=30))) < timedelta(minutes=1)
    assert await credit_svc.on_trial(db, ws)
    tx = (await db.scalars(select(CreditTransaction).where(CreditTransaction.workspace_id == ws.id))).all()
    assert [(t.kind, t.delta, t.balance_after) for t in tx] == [(CreditKind.TRIAL_GRANT, 100, 100)]
    user = await db.scalar(select(User).where(User.email == body["email"]))
    assert user.phone == "+20 100 123 4567" and user.password_hash != body["password"]

    # A real (non-demo) campaign can start on trial credits.
    assert (await anon.post("/api/v1/campaigns", json={**campaign, "start": False})).status_code == 201


async def test_signup_uses_the_admin_trial_settings(anon, db, outbox):
    s = await credit_svc.platform_settings(db)
    old = (s.trial_days, s.trial_credits)
    s.trial_days, s.trial_credits = 7, 25
    await db.commit()
    try:
        body = signup()
        r = await anon.post("/api/v1/auth/register", json=body)
        assert r.status_code == 201, r.text
        await approve_signup(body["email"])
        await anon.post("/api/v1/auth/email/verify", json={"token": link_token(outbox[-1])})
        ws = await db.get(Workspace, uuid.UUID(r.json()["workspace_id"]))
        await db.refresh(ws)
        assert ws.credit_balance == 25
        assert abs(ws.trial_ends_at - (datetime.now(UTC) + timedelta(days=7))) < timedelta(minutes=1)
    finally:
        s.trial_days, s.trial_credits = old
        await db.commit()


async def test_signup_rejects_taken_email_any_case(anon, owner):
    r = await anon.post("/api/v1/auth/register", json=signup(email=owner[0].email.upper()))
    assert r.status_code == 409 and r.json()["error"]["code"] == "email_taken"


@pytest.mark.parametrize(
    "bad",
    [
        {"password": "short"},
        {"phone": "call me"},
        {"phone": "12"},
        {"email": "not-an-email"},
        {"company": " "},
        {"locale": "fr"},
        {"nationality": "XX"},
        {"nationality": ""},
    ],
)
async def test_signup_validates_input(anon, bad):
    assert (await anon.post("/api/v1/auth/register", json=signup(**bad))).status_code == 422


async def test_signup_is_rate_limited_per_ip(anon, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "signup_limit_per_hour", 2)
    for _ in range(2):
        assert (await anon.post("/api/v1/auth/register", json=signup())).status_code == 201
    r = await anon.post("/api/v1/auth/register", json=signup())
    assert r.status_code == 429 and r.json()["error"]["code"] == "rate_limited"


async def test_public_trial_terms(anon):
    r = await anon.get("/api/v1/public/trial")
    assert r.status_code == 200 and r.json() == {"trial_days": 30, "trial_credits": 100, "credits_per_contact": 1}
