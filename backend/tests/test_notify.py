"""Notifications: admin policy and user choices, the bell, the outbox, broadcasts and unsubscribe."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.models import Notification, NotificationDelivery, PlatformSettings, TelegramAccount, User
from app.models.enums import CreditKind, DeliveryStatus, TelegramLinkStatus
from app.services import credits as credit_svc
from app.services.notify import notify
from app.services.notify.catalog import KINDS, channels_for
from app.services.notify.delivery import MAX_ATTEMPTS, deliver_due
from app.services.notify.dispatcher import unsubscribe_token
from tests.conftest import deliver_all, login, make_user


@pytest.fixture
def telegram(monkeypatch):
    calls: list[dict] = []

    async def fake_send(token, method, payload):
        calls.append(payload)
        return {"message_id": len(calls)}

    monkeypatch.setattr("app.services.notifications._send", fake_send)
    monkeypatch.setattr(get_settings(), "telegram_bot_token", "bot-token")
    return calls


@pytest.fixture
def emails(monkeypatch):
    sent: list[dict] = []

    async def fake_send(to, subject, text, html=None, headers=None):
        sent.append({"to": to, "subject": subject, "text": text, "headers": headers or {}})
        return True

    monkeypatch.setattr("app.services.mailer.send_email", fake_send)
    monkeypatch.setattr("app.services.mailer.configured", lambda: True)
    return sent


@pytest.fixture
async def policy(db):
    """Restore the platform's notification policy after the test."""
    s = await credit_svc.platform_settings(db)
    saved, rate = dict(s.notification_policy or {}), s.email_rate_per_minute
    s.email_rate_per_minute = 100_000  # other tests leave queued emails; don't let the pace hold ours back
    await db.commit()
    yield s
    s = await db.get(PlatformSettings, 1)
    s.notification_policy, s.email_rate_per_minute = saved, rate
    await db.commit()


async def link_telegram(db, user: User, workspace_id, chat_id: int | None = None) -> int:
    chat = chat_id or int(uuid.uuid4().int % 10**9)
    db.add(
        TelegramAccount(
            user_id=user.id,
            workspace_id=workspace_id,
            telegram_user_id=int(uuid.uuid4().int % 10**9),
            chat_id=chat,
            status=TelegramLinkStatus.APPROVED,
        )
    )
    await db.commit()
    return chat


async def notes_of(db, user_id, kind: str) -> list[Notification]:
    return list(
        (await db.scalars(select(Notification).where(Notification.user_id == user_id, Notification.kind == kind))).all()
    )


async def channels_of(db, note: Notification) -> set[str]:
    rows = await db.scalars(select(NotificationDelivery.channel).where(NotificationDelivery.notification_id == note.id))
    return set(rows.all())


def test_policy_and_user_choices_combine():
    kind = KINDS["campaign_completed"]
    assert channels_for({}, {}, kind) == {"in_app", "email", "telegram"}
    assert channels_for({}, {"campaign_completed": {"email": False}}, kind) == {"in_app", "telegram"}
    off = {"campaign_completed": {"channels": {"telegram": False}}}
    assert channels_for(off, {}, kind) == {"in_app", "email"}
    locked = {"campaign_completed": {"user_can_disable": False}}
    assert channels_for(locked, {"campaign_completed": {"email": False}}, kind) == {"in_app", "email", "telegram"}
    assert channels_for({"campaign_completed": {"enabled": False}}, {}, kind) == set()
    # Security kinds ignore the user's choices.
    assert "email" in channels_for({}, {"password_changed": {"email": False}}, KINDS["password_changed"])


async def test_notify_queues_reachable_channels_only(db, policy):
    user, ws = await make_user(db)
    assert await notify(db, "credits_added", users=[user], params={"credits": 5, "balance": 5}) == 1
    await db.commit()
    [note] = await notes_of(db, user.id, "credits_added")
    assert note.in_app and note.title == "5 credits added"
    assert await channels_of(db, note) == {"email"}  # no Telegram linked: nothing queued for it

    await link_telegram(db, user, ws.id)
    user.locale = "ar"
    user.email_verified_at = None  # unconfirmed inbox: only security emails
    await db.commit()
    await notify(db, "credits_added", users=[user], params={"credits": 5, "balance": 10})
    await notify(db, "password_changed", users=[user])
    await db.commit()
    newest = max(await notes_of(db, user.id, "credits_added"), key=lambda n: n.created_at)
    assert newest.title == "أُضيف 5 رصيد"
    assert await channels_of(db, newest) == {"telegram"}
    [pw] = await notes_of(db, user.id, "password_changed")
    assert await channels_of(db, pw) == {"email", "telegram"}


async def test_admin_kinds_reach_platform_admins_only(db, policy):
    admin, _ = await make_user(db)
    admin.is_superuser = True
    member, ws = await make_user(db)
    await db.commit()
    await notify(db, "admin_new_user", workspace_id=ws.id, params={"email": "x@y.z"})
    await db.commit()
    assert await notes_of(db, admin.id, "admin_new_user")
    assert not await notes_of(db, member.id, "admin_new_user")


async def test_low_balance_is_told_once_when_crossing(db, policy):
    user, ws = await make_user(db, billing_exempt=False)
    await credit_svc.grant(db, ws.id, 12, CreditKind.PURCHASE)
    await credit_svc.charge(db, ws.id, 1)  # 11: still above
    await credit_svc.charge(db, ws.id, 2)  # 9: crossed
    await credit_svc.charge(db, ws.id, 1)  # 8: already below
    await db.commit()
    [note] = await notes_of(db, user.id, "credits_low")
    assert note.params == {"balance": 9}


async def test_outbox_sends_retries_and_paces_email(db, policy, emails, telegram):
    user, ws = await make_user(db)
    chat = await link_telegram(db, user, ws.id)
    await notify(db, "topup_rejected", users=[user], params={"reason": "blurry receipt"}, link="/app/billing")
    await db.commit()
    await deliver_all()
    assert any(e["to"] == user.email and "blurry receipt" in e["text"] for e in emails)
    assert any(t["chat_id"] == chat and "blurry receipt" in t["text"] for t in telegram)

    # A failing send retries later, then gives up.
    async def broken(*a, **kw):
        return False

    import app.services.mailer as mailer

    real = mailer.send_email
    mailer.send_email = broken
    try:
        await notify(db, "topup_rejected", users=[user], params={"reason": "again"}, only_channels=["email"])
        await db.commit()
        await deliver_due(db)
        row = await db.scalar(
            select(NotificationDelivery)
            .join(Notification, Notification.id == NotificationDelivery.notification_id)
            .where(Notification.user_id == user.id, NotificationDelivery.status == DeliveryStatus.PENDING)
        )
        assert row.attempts == 1 and row.next_attempt_at > datetime.now(UTC)
        row.attempts = MAX_ATTEMPTS - 1
        row.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
        await db.commit()
        await deliver_due(db)
        await db.refresh(row)
        assert row.status == DeliveryStatus.FAILED and row.attempts == MAX_ATTEMPTS
    finally:
        mailer.send_email = real

    # Email pace: at most email_rate_per_minute sends a minute.
    policy.email_rate_per_minute = 1
    await db.commit()
    others = [(await make_user(db))[0] for _ in range(3)]
    await notify(db, "announcement", users=others, params={"title_en": "Hi"}, only_channels=["email"])
    await db.commit()
    await deliver_all()
    sent_to = {e["to"] for e in emails} & {u.email for u in others}
    assert len(sent_to) <= 1


async def test_bell_api(app, db, policy):
    user, _ = await make_user(db)
    await notify(db, "credits_added", users=[user], params={"credits": 3, "balance": 3}, link="/app/billing")
    await notify(db, "trial_ended", users=[user])
    await db.commit()
    c = await login(app, user.email)
    try:
        page = (await c.get("/api/v1/notifications")).json()
        assert page["unread"] == 2 and page["total"] == 2
        first = page["items"][0]
        assert (await c.post(f"/api/v1/notifications/{first['id']}/read")).status_code == 200
        assert (await c.get("/api/v1/notifications/unread-count")).json() == {"unread": 1}
        assert (await c.post("/api/v1/notifications/read-all")).status_code == 200
        assert (await c.get("/api/v1/notifications", params={"unread": True})).json()["total"] == 0
        other, _ = await make_user(db)
        await notify(db, "trial_ended", users=[other])
        await db.commit()
        [theirs] = await notes_of(db, other.id, "trial_ended")
        assert (await c.post(f"/api/v1/notifications/{theirs.id}/read")).status_code == 404
    finally:
        await c.aclose()


async def test_preferences_follow_policy(app, db, policy):
    user, _ = await make_user(db)
    c = await login(app, user.email)
    try:
        prefs = (await c.get("/api/v1/notifications/preferences")).json()
        keys = {k["key"]: k for k in prefs["kinds"]}
        assert "admin_new_user" not in keys and keys["password_changed"]["locked"]
        r = await c.put(
            "/api/v1/notifications/preferences",
            json={"prefs": {"marketing": {"email": False}, "password_changed": {"email": False}}},
        )
        keys = {k["key"]: k for k in r.json()["kinds"]}
        assert keys["marketing"]["channels"]["email"] == {"allowed": True, "on": False}
        assert keys["password_changed"]["channels"]["email"]["on"]
        await db.refresh(user)
        assert user.notification_prefs == {"marketing": {"email": False}}

        policy.notification_policy = {"marketing": {"user_can_disable": False}, "trial_ended": {"enabled": False}}
        await db.commit()
        keys = {k["key"]: k for k in (await c.get("/api/v1/notifications/preferences")).json()["kinds"]}
        assert keys["marketing"]["locked"] and keys["marketing"]["channels"]["email"]["on"]
        assert "trial_ended" not in keys
    finally:
        await c.aclose()


async def test_unsubscribe_link(app, db, policy, emails):
    user, _ = await make_user(db)
    await notify(db, "marketing", users=[user], params={"title_en": "Offer", "body_en": "20% off"})
    await db.commit()
    await deliver_all()
    mail = next(e for e in emails if e["to"] == user.email)
    assert "List-Unsubscribe" in mail["headers"] and "/unsubscribe?token=" in mail["text"]

    import httpx

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as anon:
        assert (await anon.post("/api/v1/notifications/unsubscribe", params={"token": "nope"})).status_code == 400
        token = unsubscribe_token(user.id, "marketing")
        r = await anon.post("/api/v1/notifications/unsubscribe", params={"token": token})
        assert r.status_code == 200 and r.json() == {"kind": "marketing"}
    await db.refresh(user)
    assert user.notification_prefs["marketing"]["email"] is False
    await notify(db, "marketing", users=[user], params={"title_en": "Offer 2"})
    await db.commit()
    newest = max(await notes_of(db, user.id, "marketing"), key=lambda n: n.created_at)
    assert await channels_of(db, newest) == set()  # still on the bell, no more emails


async def test_admin_policy_and_broadcast(app, db, policy, emails, telegram):
    admin, _ = await make_user(db)
    admin.is_superuser = True
    await db.commit()
    a = await login(app, admin.email)
    targets = [(await make_user(db)) for _ in range(2)]
    chat = await link_telegram(db, targets[0][0], targets[0][1].id)
    try:
        pol = (await a.get("/api/v1/admin/notifications/policy")).json()
        assert {k["key"] for k in pol["kinds"]} == set(KINDS)
        r = await a.put(
            "/api/v1/admin/notifications/policy",
            json={"policy": {"marketing": {"channels": {"telegram": True}}, "bogus": {}}, "email_rate_per_minute": 30},
        )
        assert r.status_code == 200
        await db.refresh(policy)
        assert set(policy.notification_policy) == {"marketing"} and policy.email_rate_per_minute == 30

        audience = {"type": "users", "ids": [str(u.id) for u, _ in targets]}
        assert (await a.post("/api/v1/admin/broadcasts/preview", json=audience)).json() == {"recipients": 2}
        assert (await a.post("/api/v1/admin/broadcasts/preview", json={"type": "users"})).status_code == 422
        body = {
            "kind": "announcement",
            "title_ar": "ميزة جديدة",
            "title_en": "New feature",
            "body_ar": "جرّب التصدير الجديد",
            "body_en": "Try the new export",
            "link": "/app/leads",
            "audience": audience,
            "channels": ["in_app", "telegram"],
        }
        assert (await a.post("/api/v1/admin/broadcasts", json={**body, "link": "javascript:x"})).status_code == 422
        r = await a.post("/api/v1/admin/broadcasts", json=body)
        assert r.status_code == 201, r.text
        bid = r.json()["id"]
        await deliver_all()
        for user, _ in targets:
            [note] = await notes_of(db, user.id, "announcement")
            assert note.title == "New feature" and str(note.broadcast_id) == bid
        assert any(t["chat_id"] == chat and "New feature" in t["text"] for t in telegram)
        assert not any(e["to"] in {u.email for u, _ in targets} for e in emails)  # email wasn't picked

        page = (await a.get("/api/v1/admin/broadcasts")).json()
        row = next(b for b in page["items"] if b["id"] == bid)
        assert row["status"] == "sent" and row["recipients"] == 2
        assert row["stats"]["in_app"] == 2 and row["stats"]["telegram"] == {"sent": 1}

        assert (await a.post("/api/v1/admin/broadcasts/test", json=body)).status_code == 200
        found = (await a.get("/api/v1/admin/notifications/recipients", params={"q": targets[1][0].email})).json()
        assert [u["id"] for u in found] == [str(targets[1][0].id)]

        user_client = await login(app, targets[1][0].email)
        try:
            assert (await user_client.get("/api/v1/admin/notifications/policy")).status_code == 403
        finally:
            await user_client.aclose()
    finally:
        await a.aclose()


async def test_admin_actions_notify_the_client(app, db, policy):
    admin, _ = await make_user(db)
    admin.is_superuser = True
    client, ws = await make_user(db, billing_exempt=False)
    await db.commit()
    a = await login(app, admin.email)
    try:
        r = await a.post(f"/api/v1/admin/workspaces/{ws.id}/adjust", json={"delta": 15, "note": "goodwill"})
        assert r.status_code == 200
        [note] = await notes_of(db, client.id, "credits_added")
        assert note.params == {"credits": 15, "balance": 15}
        assert (await a.patch(f"/api/v1/admin/workspaces/{ws.id}", json={"suspended": True})).status_code == 200
        assert await notes_of(db, client.id, "account_suspended")
    finally:
        await a.aclose()


async def test_locale_endpoint(app, db):
    user, _ = await make_user(db)
    c = await login(app, user.email)
    try:
        assert (await c.put("/api/v1/auth/locale", json={"locale": "ar"})).status_code == 200
        assert (await c.put("/api/v1/auth/locale", json={"locale": "fr"})).status_code == 422
    finally:
        await c.aclose()
    await db.refresh(user)
    assert user.locale == "ar"


async def test_one_bad_message_never_blocks_or_repeats_the_batch(db, policy, monkeypatch):
    """A crash on one row is recorded on that row; what was sent before it is not sent again."""
    sent: list[str] = []

    async def fake_send(to, subject, text, html=None, headers=None):
        if "BOOM" in subject:
            raise ValueError("unexpected")
        sent.append(to)  # the header clean-up itself lives in the real mailer (test_mailer_keeps_headers_on_one_line)
        return True

    monkeypatch.setattr("app.services.mailer.send_email", fake_send)
    monkeypatch.setattr("app.services.mailer.configured", lambda: True)
    good, bad, after = [(await make_user(db))[0] for _ in range(3)]
    for u, title in ((good, "Hello\nBcc: x@y.z"), (bad, "BOOM"), (after, "Fine")):
        await notify(db, "announcement", users=[u], params={"title_en": title}, only_channels=["email"])
        await db.commit()
    await deliver_all()
    assert good.email in sent and after.email in sent
    first = list(sent)
    await deliver_all()
    assert sent == first  # nothing re-sent
    [note] = await notes_of(db, bad.id, "announcement")
    row = await db.scalar(select(NotificationDelivery).where(NotificationDelivery.notification_id == note.id))
    assert row.status == DeliveryStatus.PENDING and row.attempts == 1 and "ValueError" in row.last_error


def test_mailer_keeps_headers_on_one_line():
    from app.services.mailer import _one_line

    assert _one_line("Contact: Omar\r\nBcc: x@y.z") == "Contact: Omar Bcc: x@y.z"


def test_long_telegram_text_keeps_whole_entities():
    from app.services.notify.templates import render_telegram

    text = render_telegram("A & B", "x&y " * 2000, "/app")
    assert "&amp;" in text and text.count("&") == text.count("&amp;")
    assert len(text.replace("&amp;", "&")) < 4096 and "…" in text


async def test_telegram_skips_deactivated_users(db, policy, telegram):
    user, ws = await make_user(db)
    chat = await link_telegram(db, user, ws.id)
    await notify(db, "trial_ended", users=[user], only_channels=["telegram"])
    user.is_active = False
    await db.commit()
    await deliver_all()
    assert not any(t["chat_id"] == chat for t in telegram)


async def test_manual_topup_approval_does_not_notify_admins(db, policy):
    from decimal import Decimal

    from app.models import TopUpRequest
    from app.services.notify import events

    admin, _ = await make_user(db)
    admin.is_superuser = True
    client, ws = await make_user(db)
    topup = TopUpRequest(
        workspace_id=ws.id, credits=5, amount=Decimal("1.00"), currency="USD", method="instapay", status="approved"
    )
    db.add(topup)
    await db.flush()
    await events.payment_received(db, topup, manual=True)
    await db.commit()
    assert await notes_of(db, client.id, "topup_approved")
    assert not await notes_of(db, admin.id, "admin_new_payment")


async def test_broadcast_resume_never_duplicates(db, policy):
    from app.models import Broadcast
    from app.services.notify import broadcast as bc

    users = [(await make_user(db))[0] for _ in range(2)]
    b = Broadcast(
        kind="announcement",
        title_en="Resume me",
        audience={"type": "users", "ids": [str(u.id) for u in users]},
        channels=["in_app"],
        status="sending",
    )
    db.add(b)
    await db.flush()
    # Interrupted after the first person, a while ago.
    await notify(
        db, "announcement", users=users[:1], params=bc.params_of(b), only_channels=["in_app"], broadcast_id=b.id
    )
    b.updated_at = datetime.now(UTC) - timedelta(minutes=bc.STALE_MINUTES + 1)
    await db.commit()
    assert await bc.resume_stale(db) >= 1
    await db.refresh(b)
    assert b.status == "sent" and b.recipients == 2
    for u in users:
        assert len(await notes_of(db, u.id, "announcement")) == 1
    await bc.launch(b.id)  # already sent: does nothing
    assert len(await notes_of(db, users[0].id, "announcement")) == 1


async def test_rejected_signups_are_not_in_broadcast_audiences(db):
    from app.models.enums import ApprovalStatus
    from app.services.notify import audience

    ok, _ = await make_user(db)
    rejected, _ = await make_user(db)
    rejected.approval_status = ApprovalStatus.REJECTED
    await db.commit()
    ids = set((await db.scalars(audience.user_ids_query({"type": "all"}))).all())
    assert ok.id in ids and rejected.id not in ids


async def test_auto_approved_telegram_link_is_not_repeated_in_the_chat(app, db, policy):
    import httpx

    user, ws = await make_user(db)
    c = await login(app, user.email)
    try:
        code = (await c.post("/api/v1/telegram/link-code")).json()["code"]
    finally:
        await c.aclose()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as bot:
        r = await bot.post(
            "/api/v1/telegram/link",
            headers={"x-service-token": get_settings().telegram_service_token},
            json={"code": code, "telegram_user_id": int(uuid.uuid4().int % 10**9), "chat_id": 4242},
        )
        assert r.json()["status"] == "approved"
    [note] = await notes_of(db, user.id, "telegram_linked")
    assert "telegram" not in await channels_of(db, note)


async def test_broadcast_link_must_stay_on_site(app, db, policy):
    admin, _ = await make_user(db)
    admin.is_superuser = True
    await db.commit()
    a = await login(app, admin.email)
    try:
        body = {"title_en": "x", "audience": {"type": "admins"}, "channels": ["in_app"], "link": "//evil.example"}
        assert (await a.post("/api/v1/admin/broadcasts/test", json=body)).status_code == 422
    finally:
        await a.aclose()
