"""Forgot / reset password, email confirmation, and sessions dying with the password they were issued for."""

import uuid

import httpx
import pytest
from sqlalchemy import select

from app.core.redis import async_redis
from app.core.security import create_purpose_token, password_fingerprint
from app.models import CreditTransaction, User, Workspace
from app.models.enums import CreditKind
from app.services import accounts
from tests.conftest import PASSWORD, link_token, login, make_user


@pytest.fixture(autouse=True)
async def _fresh_limits():
    async def clear():
        r = async_redis()
        keys = []
        for pattern in ("pwreset*", "verify-resend*", "signup*"):
            keys += [k async for k in r.scan_iter(f"ratelimit:{pattern}")]
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


async def forgot(c, email: str) -> httpx.Response:
    return await c.post("/api/v1/auth/password/forgot", json={"email": email})


async def test_forgot_password_emails_a_working_one_time_link(app, anon, db, owner, outbox):
    user = owner[0]
    session = await login(app, user.email)  # an existing session, e.g. on a stolen laptop
    r = await forgot(anon, user.email.upper())
    assert r.status_code == 202
    [mail] = outbox
    assert mail["to"] == user.email and "/reset-password?token=" in mail["text"]
    token = link_token(mail)

    r = await anon.post("/api/v1/auth/password/reset", json={"token": token, "password": "a-brand-new-password"})
    assert r.status_code == 200, r.text
    # Works once: the token was bound to the old password.
    again = await anon.post("/api/v1/auth/password/reset", json={"token": token, "password": "yet-another-password"})
    assert again.status_code == 400 and again.json()["error"]["code"] == "invalid_token"

    # Old password and old sessions are gone; the new password works.
    assert (await anon.post("/api/v1/auth/login", json={"email": user.email, "password": PASSWORD})).status_code == 401
    assert (await session.get("/api/v1/auth/me")).status_code == 401
    await session.aclose()
    ok = await anon.post("/api/v1/auth/login", json={"email": user.email, "password": "a-brand-new-password"})
    assert ok.status_code == 200


async def test_forgot_password_does_not_reveal_accounts(anon, outbox):
    r = await forgot(anon, f"nobody-{uuid.uuid4().hex[:6]}@example.com")
    assert r.status_code == 202 and "If an account exists" in r.json()["message"]
    assert outbox == []


async def test_inactive_users_get_no_reset_email(anon, db, outbox):
    user, _ = await make_user(db)
    user.is_active = False
    await db.commit()
    assert (await forgot(anon, user.email)).status_code == 202
    assert outbox == []


async def test_forgot_password_is_rate_limited(anon, owner, outbox):
    for _ in range(3):
        assert (await forgot(anon, owner[0].email)).status_code == 202
    r = await forgot(anon, owner[0].email)  # per address
    assert r.status_code == 429 and len(outbox) == 3


@pytest.mark.parametrize(
    "token",
    [
        "not-a-real-token-at-all",
        # Right purpose, wrong password fingerprint (an old link).
        lambda u: create_purpose_token(accounts.RESET, u.id, 60, pv="0" * 16),
        # A confirmation link can't reset a password.
        lambda u: create_purpose_token(accounts.VERIFY, u.id, 60, pv=password_fingerprint(u.password_hash)),
        # Expired.
        lambda u: create_purpose_token(accounts.RESET, u.id, -1, pv=password_fingerprint(u.password_hash)),
    ],
)
async def test_reset_rejects_bad_tokens(anon, owner, token):
    user = owner[0]
    value = token(user) if callable(token) else token
    r = await anon.post("/api/v1/auth/password/reset", json={"token": value, "password": "a-brand-new-password"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_token"


async def test_reset_validates_the_new_password(anon, owner):
    token = create_purpose_token(accounts.RESET, owner[0].id, 60, pv=password_fingerprint(owner[0].password_hash))
    r = await anon.post("/api/v1/auth/password/reset", json={"token": token, "password": "short"})
    assert r.status_code == 422


async def test_session_token_is_not_a_reset_token(app, anon, owner):
    me = (await anon.post("/api/v1/auth/login", json={"email": owner[0].email, "password": PASSWORD})).json()
    r = await anon.post(
        "/api/v1/auth/password/reset", json={"token": me["access_token"], "password": "a-brand-new-password"}
    )
    assert r.status_code == 400


async def test_changing_password_keeps_this_session_and_ends_others(app, owner):
    a = await login(app, owner[0].email)
    b = await login(app, owner[0].email)
    try:
        r = await a.post(
            "/api/v1/auth/password", json={"current_password": PASSWORD, "new_password": "a-brand-new-password"}
        )
        assert r.status_code == 200
        assert (await a.get("/api/v1/auth/me")).status_code == 200
        assert (await b.get("/api/v1/auth/me")).status_code == 401
    finally:
        await a.aclose()
        await b.aclose()


async def signup(anon) -> dict:
    body = {
        "full_name": "Omar Saleh",
        "company": "Gulf Dental",
        "email": f"omar-{uuid.uuid4().hex[:8]}@example.com",
        "phone": "+971 50 123 4567",
        "password": "a-long-enough-password",
        "locale": "en",
    }
    r = await anon.post("/api/v1/auth/register", json=body)
    assert r.status_code == 201, r.text
    anon.headers["x-csrf-token"] = r.json()["csrf_token"]
    return {**body, "workspace_id": r.json()["workspace_id"]}


async def test_confirmation_grants_the_trial_once(anon, db, outbox):
    body = await signup(anon)
    token = link_token(outbox[0])
    assert outbox[0]["subject"].startswith("Confirm")
    for _ in range(2):  # opening the link twice is fine and grants nothing more
        assert (await anon.post("/api/v1/auth/email/verify", json={"token": token})).status_code == 200
    user = await db.scalar(select(User).where(User.email == body["email"]))
    assert user.email_verified_at is not None
    grants = (
        await db.scalars(
            select(CreditTransaction)
            .join(Workspace, Workspace.id == CreditTransaction.workspace_id)
            .where(CreditTransaction.created_by == user.id, CreditTransaction.kind == CreditKind.TRIAL_GRANT)
        )
    ).all()
    assert len(grants) == 1
    me = (await anon.get("/api/v1/auth/me")).json()
    assert me["user"]["email_verified_at"] is not None
    r = await anon.post("/api/v1/auth/email/resend")
    assert r.status_code == 409 and r.json()["error"]["code"] == "already_verified"


async def test_confirmation_link_is_bound_to_the_address(anon, db, outbox):
    body = await signup(anon)
    user = await db.scalar(select(User).where(User.email == body["email"]))
    stale = create_purpose_token(accounts.VERIFY, user.id, 60, email="old-address@example.com")
    r = await anon.post("/api/v1/auth/email/verify", json={"token": stale})
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_token"
    reset = create_purpose_token(accounts.RESET, user.id, 60, email=user.email)  # wrong purpose
    assert (await anon.post("/api/v1/auth/email/verify", json={"token": reset})).status_code == 400


async def test_resend_confirmation_is_limited(anon, outbox):
    await signup(anon)
    for _ in range(3):
        assert (await anon.post("/api/v1/auth/email/resend")).status_code == 202
    assert (await anon.post("/api/v1/auth/email/resend")).status_code == 429
    assert len(outbox) == 4  # the signup email + three resends


async def test_password_reset_also_confirms_the_email(anon, db, outbox):
    body = await signup(anon)
    outbox.clear()
    await forgot(anon, body["email"])
    r = await anon.post(
        "/api/v1/auth/password/reset", json={"token": link_token(outbox[0]), "password": "a-brand-new-password"}
    )
    assert r.status_code == 200
    user = await db.scalar(select(User).where(User.email == body["email"]))
    assert user.email_verified_at is not None
    ws = await db.get(Workspace, uuid.UUID(body["workspace_id"]))
    await db.refresh(ws)
    assert ws.credit_balance == 100


async def test_emails_are_logged_when_smtp_is_not_configured(caplog):
    from app.services.mailer import send_email

    assert await send_email("x@example.com", "Hello", "Link: http://localhost:3000/verify-email?token=abc") is False
    assert "verify-email?token=abc" in caplog.text
