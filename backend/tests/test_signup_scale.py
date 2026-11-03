"""Duplicate detection under load: busy shared values are ignored, rotating traits are capped, counts are stored."""

import uuid

from sqlalchemy import func, select

from app.models import AccountSignal, Notification, NotificationDelivery, User
from app.models.enums import ApprovalStatus, SignalKind
from app.services import signup_review as review
from tests.conftest import make_user


async def _users(db, n: int) -> list[User]:
    return [(await make_user(db))[0] for _ in range(n)]


async def test_a_busy_shared_ip_is_not_evidence(db):
    """A mobile carrier's NAT puts many people behind one IP: past the cap it stops matching anyone."""
    ip = f"41.40.{uuid.uuid4().int % 250}.{uuid.uuid4().int % 250}"
    few = await _users(db, 3)
    for u in few:
        await review.record(db, u, ip=ip)
    await db.commit()
    assert {m.user_id for m in await review.matches(db, few[0].id)} == {few[1].id, few[2].id}

    crowd = await _users(db, review.WEAK_HOT[SignalKind.IP] + 2)
    for u in crowd:
        await review.record(db, u, ip=ip)
    await db.commit()
    assert await review.matches(db, few[0].id) == []


async def test_a_shared_phone_still_matches_alongside_a_busy_ip(db):
    ip = "41.41.1.1"
    a, b, *crowd = await _users(db, review.WEAK_HOT[SignalKind.IP] + 4)
    phone_value = f"5{uuid.uuid4().int % 10**8:08d}"
    for u in (a, b):
        u.phone = phone_value
        await review.record(db, u, ip=ip, with_identity=True)
    for u in crowd:
        await review.record(db, u, ip=ip)
    await db.commit()
    [m] = await review.matches(db, a.id)
    assert m.user_id == b.id and m.kinds == [SignalKind.PHONE] and m.strong


async def test_rotating_ips_keep_only_the_latest(db):
    [u] = await _users(db, 1)
    for i in range(review.KEEP[SignalKind.IP] + 5):
        await review.record(db, u, ip=f"41.42.0.{i + 1}")
        await db.commit()
    count = await db.scalar(
        select(func.count()).where(AccountSignal.user_id == u.id, AccountSignal.kind == SignalKind.IP)
    )
    assert count == review.KEEP[SignalKind.IP]
    newest = await db.scalar(
        select(AccountSignal.value)
        .where(AccountSignal.user_id == u.id, AccountSignal.kind == SignalKind.IP)
        .order_by(AccountSignal.last_seen_at.desc())
        .limit(1)
    )
    assert newest == f"41.42.0.{review.KEEP[SignalKind.IP] + 5}"


async def test_record_reports_only_new_values(db):
    [u] = await _users(db, 1)
    device = uuid.uuid4().hex
    assert await review.record(db, u, device=device) == [(SignalKind.DEVICE, device)]
    assert await review.record(db, u, device=device) == []  # seen again: only last_seen moves
    await db.commit()


async def test_counts_are_stored_on_both_accounts(db):
    a, b = await _users(db, 2)
    device = uuid.uuid4().hex
    await review.record(db, a, device=device)
    await review.record(db, b, device=device)
    await db.commit()
    await review.refresh_counts(b.id)
    for u in (a, b):
        await db.refresh(u)
        assert (u.dup_matches, u.dup_strong) == (1, 1)


async def test_approval_email_reaches_an_unconfirmed_inbox(db, platform_admin):
    [u] = await _users(db, 1)
    u.email_verified_at = None
    u.approval_status = ApprovalStatus.PENDING
    await db.commit()
    assert await review.approve(db, u, platform_admin[0].id)
    await db.commit()
    q = select(Notification).where(Notification.user_id == u.id, Notification.kind == "account_approved")
    note = await db.scalar(q)
    assert "Confirm your email" in note.body
    channels = (
        await db.scalars(select(NotificationDelivery.channel).where(NotificationDelivery.notification_id == note.id))
    ).all()
    assert "email" in channels


def test_pending_signup_email_says_it_is_under_review():
    from app.services.accounts import _render

    user = User(email="x@example.com", full_name="X", locale="en", approval_status=ApprovalStatus.PENDING)
    _, text, _ = _render("verify", user, "https://rasd.test/verify")
    assert "reviewing" in text
    user.approval_status = ApprovalStatus.APPROVED
    _, text, _ = _render("verify", user, "https://rasd.test/verify")
    assert "reviewing" not in text


async def test_a_crowded_phone_still_flags_every_account(db):
    """Strong traits never go quiet: making many accounts on one phone cannot hide the next one."""
    phone_value = f"5{uuid.uuid4().int % 10**8:08d}"
    farm = await _users(db, 35)
    for u in farm:
        u.phone = phone_value
        await review.record(db, u, with_identity=True)
    await db.commit()
    found = await review.matches(db, farm[-1].id)
    assert len(found) == 34 and all(m.strong for m in found)


async def test_counts_heal_when_a_shared_ip_gets_busy(db):
    """The 11th account on one IP makes it a network: the earlier holders stop counting it as a match."""
    ip = f"41.43.{uuid.uuid4().int % 250}.{uuid.uuid4().int % 250}"
    first = await _users(db, 2)
    for u in first:
        await review.record(db, u, ip=ip)
    await db.commit()
    await review.refresh_counts(first[1].id)
    await db.refresh(first[0])
    assert first[0].dup_matches == 1
    for u in await _users(db, review.WEAK_HOT[SignalKind.IP]):
        new = await review.record(db, u, ip=ip)
        await db.commit()
        await review.refresh_counts(u.id, new)
    await db.refresh(first[0])
    assert first[0].dup_matches == 0

