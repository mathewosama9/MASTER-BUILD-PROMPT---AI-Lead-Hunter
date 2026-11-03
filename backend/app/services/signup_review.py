"""Admin review of self-signups, and spotting one person behind several accounts.

Every signup and sign-in records the traits it was seen with (`AccountSignal`): a long-lived device cookie, a hash
of browser traits, the phone, the email with aliases removed, and the public IP. Two users sharing a value are shown
to the platform admin as a possible duplicate, with the shared traits as the reason. Nothing is decided
automatically: a new self-signup waits as `pending` (no trial credits) until the admin approves or rejects it, from
the dashboard or from the Telegram buttons.

Built to stay cheap with many users:
- a weak value shared by many accounts (a mobile carrier's IP, a popular phone model's traits) identifies a
  network, not a person, so it is ignored (`WEAK_HOT`); strong values (browser cookie, phone, email) always count,
  so making 50 accounts from one phone cannot hide the 51st; every lookup stops at PER_VALUE accounts per value;
- rotating traits (IP, browser hash, browser cookie) keep only each user's most recent values (`KEEP`);
- each user's match counts are stored on the user row and refreshed after the request commits, one short
  single-row update at a time (`refresh_counts`), so the admin list reads columns and concurrent sign-ins of linked
  accounts never lock each other's rows.
"""

import ipaddress
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import delete, func, literal_column, or_, select, true, tuple_, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.db import get_sessionmaker
from app.models import AccountSignal, User
from app.models.enums import ApprovalStatus, SignalKind
from app.services import accounts
from app.services import credits as credit_svc
from app.services.notify import notify

DEVICE_COOKIE = "lh_device"
DEVICE_COOKIE_DAYS = 730
# These point at the same person or browser. A shared IP (offices, mobile carrier NAT) or browser-traits hash (many
# identical phones share one) is weak on its own; both together count as strong.
STRONG = {SignalKind.DEVICE, SignalKind.PHONE, SignalKind.EMAIL}
WEAK_PAIR = {SignalKind.FINGERPRINT, SignalKind.IP}
_GMAIL = {"gmail.com", "googlemail.com"}
# Weak traits shared by more other accounts than this are a network or a phone model, not a person: ignored.
WEAK_HOT = {SignalKind.IP: 10, SignalKind.FINGERPRINT: 10}
# Strong traits never go quiet however many accounts share them (a crowded phone or browser is a trial farm). Each
# value lists at most this many other accounts, so one crowded value cannot make a query unbounded.
PER_VALUE = 50
# Traits that rotate (IPs, browser hashes, cleared cookies): keep only each user's most recent values.
KEEP = {SignalKind.IP: 20, SignalKind.FINGERPRINT: 10, SignalKind.DEVICE: 20}
# Accounts recomputed after one change, at most (fan-out bound for the background refresh).
REFRESH_MAX = 200
log = logging.getLogger(__name__)

Signal = tuple[str, str]  # (kind, value)

REASON_LABELS = {
    "en": {
        SignalKind.DEVICE: "same browser",
        SignalKind.FINGERPRINT: "same device",
        SignalKind.PHONE: "same phone",
        SignalKind.EMAIL: "same email (alias)",
        SignalKind.IP: "same IP",
    },
    "ar": {
        SignalKind.DEVICE: "نفس المتصفح",
        SignalKind.FINGERPRINT: "نفس الجهاز",
        SignalKind.PHONE: "نفس رقم الموبايل",
        SignalKind.EMAIL: "نفس الإيميل (بصيغة تانية)",
        SignalKind.IP: "نفس الـ IP",
    },
}


def canonical_email(email: str) -> str:
    """name+tag@x.com and n.a.m.e@gmail.com reach the same inbox as name@x.com / name@gmail.com."""
    local, _, domain = email.strip().lower().partition("@")
    local = local.split("+", 1)[0]
    if domain in _GMAIL:
        local, domain = local.replace(".", ""), "gmail.com"
    return f"{local}@{domain}"


def canonical_phone(phone: str | None) -> str | None:
    """The last 9 digits: the same number written with or without the country code or a leading 0."""
    digits = re.sub(r"\D", "", phone or "")
    return digits[-9:] if len(digits) >= 7 else None


def public_ip(ip: str | None) -> str | None:
    try:
        addr = ipaddress.ip_address(ip or "")
    except ValueError:
        return None
    return str(addr) if addr.is_global else None  # internal hops say nothing about the person


def new_device_id() -> str:
    return uuid.uuid4().hex


async def record(
    db: AsyncSession,
    user: User,
    *,
    ip: str | None = None,
    device: str | None = None,
    fingerprint: str | None = None,
    user_agent: str | None = None,
    with_identity: bool = False,
) -> list[Signal]:
    """Remember what this user was seen with. `with_identity` adds the phone and canonical email (at signup).

    Returns the values new for this user; when there are any the caller runs `refresh_counts_soon` after its commit.
    """
    values: list[tuple[str, str | None]] = [
        (SignalKind.IP, public_ip(ip)),
        (SignalKind.DEVICE, device),
        (SignalKind.FINGERPRINT, fingerprint),
    ]
    if with_identity:
        values += [(SignalKind.PHONE, canonical_phone(user.phone)), (SignalKind.EMAIL, canonical_email(user.email))]
    rows = [
        {
            "id": uuid.uuid4(),
            "user_id": user.id,
            "kind": k,
            "value": v[:255],
            "last_seen_at": datetime.now(UTC),
            # The browser behind a device id, for the admin's list of the user's devices.
            "user_agent": (user_agent or "")[:400] or None if k == SignalKind.DEVICE else None,
            "ip": public_ip(ip) if k == SignalKind.DEVICE else None,
        }
        for k, v in values
        if v
    ]
    if not rows:
        return []
    stmt = insert(AccountSignal).values(rows)
    result = await db.execute(
        stmt.on_conflict_do_update(
            index_elements=["user_id", "kind", "value"],
            set_={
                "last_seen_at": stmt.excluded.last_seen_at,
                "user_agent": func.coalesce(stmt.excluded.user_agent, AccountSignal.user_agent),
                "ip": func.coalesce(stmt.excluded.ip, AccountSignal.ip),
            },
        ).returning(AccountSignal.kind, AccountSignal.value, literal_column("xmax = 0"))  # true: a fresh insert
    )
    new = [(kind, value) for kind, value, inserted in result.all() if inserted]
    for kind in {k for k, _ in new} & KEEP.keys():
        newest = (
            select(AccountSignal.id)
            .where(AccountSignal.user_id == user.id, AccountSignal.kind == kind)
            .order_by(AccountSignal.last_seen_at.desc().nulls_last())
            .limit(KEEP[SignalKind(kind)])
        )
        await db.execute(
            delete(AccountSignal).where(
                AccountSignal.user_id == user.id, AccountSignal.kind == kind, AccountSignal.id.not_in(newest)
            )
        )
    return new


@dataclass
class Match:
    """Another account that shares at least one trait with the reviewed one."""

    user_id: uuid.UUID
    email: str
    full_name: str
    approval_status: str
    is_active: bool
    created_at: datetime
    kinds: list[str] = field(default_factory=list)
    values: dict[str, str] = field(default_factory=dict)

    @property
    def strong(self) -> bool:
        return any(k in STRONG for k in self.kinds) or WEAK_PAIR <= set(self.kinds)


async def _holders(
    db: AsyncSession, user_id: uuid.UUID, only: list[Signal] | None = None
) -> dict[Signal, list[uuid.UUID]]:
    """For each of the user's values (or just `only`): up to PER_VALUE + 1 other accounts holding it. One query; each
    value's lookup is a LATERAL index probe that stops at the limit, however crowded the value is."""
    mine, peer = aliased(AccountSignal), aliased(AccountSignal)
    peers = (
        select(peer.user_id)
        .where(peer.kind == mine.kind, peer.value == mine.value, peer.user_id != user_id)
        .limit(PER_VALUE + 1)
        .lateral()
    )
    q = select(mine.kind, mine.value, peers.c.user_id).join(peers, true()).where(mine.user_id == user_id)
    if only is not None:
        if not only:
            return {}
        q = q.where(tuple_(mine.kind, mine.value).in_(only))
    out: dict[Signal, list[uuid.UUID]] = {}
    for kind, value, other in (await db.execute(q)).all():
        out.setdefault((kind, value), []).append(other)
    return out


def _usable(kind: str, others: list[uuid.UUID]) -> bool:
    limit = WEAK_HOT.get(SignalKind(kind))
    return limit is None or len(others) <= limit


async def matches(db: AsyncSession, user_id: uuid.UUID) -> list[Match]:
    """Other accounts sharing a trait with `user_id`, strongest evidence first. Busy weak values (`WEAK_HOT`) are
    skipped; strong ones always count, listing at most PER_VALUE accounts each. Two bounded queries."""
    by_user: dict[uuid.UUID, dict[str, str]] = {}
    for (kind, value), others in (await _holders(db, user_id)).items():
        if not _usable(kind, others):
            continue
        for other in others[:PER_VALUE]:
            by_user.setdefault(other, {}).setdefault(kind, value)
    if not by_user:
        return []
    users = await db.scalars(select(User).where(User.id.in_(list(by_user)), User.deleted_at.is_(None)))
    order = list(SignalKind)
    found = [
        Match(
            u.id,
            u.email,
            u.full_name,
            u.approval_status,
            u.is_active,
            u.created_at,
            kinds=sorted(by_user[u.id], key=order.index),
            values=by_user[u.id],
        )
        for u in users.all()
    ]
    return sorted(found, key=lambda m: (not m.strong, -len(m.kinds), m.created_at))


async def store_counts(db: AsyncSession, user_id: uuid.UUID, found: list[Match]) -> None:
    n, strong = len(found), sum(1 for m in found if m.strong)
    await db.execute(
        update(User)
        .where(User.id == user_id, or_(User.dup_matches != n, User.dup_strong != strong))  # no-op writes skipped
        .values(dup_matches=n, dup_strong=strong)
        .execution_options(synchronize_session=False)
    )


async def refresh_counts(user_id: uuid.UUID, changed: list[Signal] | None = None) -> list[Match]:
    """Recompute the stored counts of `user_id`, then of the accounts the change can affect: every account sharing a
    `changed` value (default: all of the user's values) that is not already a busy weak value. That includes values
    that just became busy, whose earlier holders must stop counting them. Each account is its own short
    transaction (one row lock at a time, so linked accounts signing in together cannot deadlock); at most
    REFRESH_MAX accounts per call."""
    maker = get_sessionmaker()
    async with maker() as db:
        found = await matches(db, user_id)
        await store_counts(db, user_id, found)
        holders = await _holders(db, user_id, changed)
        await db.commit()
    affected: dict[uuid.UUID, None] = {m.user_id: None for m in found}
    for (kind, _), others in holders.items():
        limit = WEAK_HOT.get(SignalKind(kind))
        if limit is None or len(others) <= limit + 1:  # usable, or just crossed the line with this user
            affected.update(dict.fromkeys(others[:PER_VALUE]))
    for other in list(affected)[:REFRESH_MAX]:
        async with maker() as db:
            await store_counts(db, other, await matches(db, other))
            await db.commit()
    return found


async def refresh_counts_soon(user_id: uuid.UUID, changed: list[Signal] | None = None) -> None:
    """Background-task wrapper: never fails the request it follows."""
    try:
        await refresh_counts(user_id, changed)
    except Exception:  # noqa: BLE001 - counts heal on the next refresh or when the admin opens the user
        log.warning("refreshing duplicate counts failed", exc_info=True)


async def after_signup(user_id: uuid.UUID) -> None:
    """Runs after the signup commits. Two signups made at the same moment cannot see each other inside their own
    transactions; now both are visible. If the account was let in without review but is likely a duplicate, the
    admins hear about it (nothing is revoked automatically)."""
    try:
        found = await refresh_counts(user_id)
        if not any(m.strong for m in found):
            return
        async with get_sessionmaker()() as db:
            user = await db.get(User, user_id)
            if user is None or user.approval_status != ApprovalStatus.APPROVED or user.reviewed_at is not None:
                return
            await notify(
                db,
                "admin_signup_suspicious",
                params=signup_params(user, "", found),
                link=f"/app/admin?tab=users&user={user.id}",
            )
            await db.commit()
    except Exception:  # noqa: BLE001
        log.warning("post-signup duplicate check failed", exc_info=True)


def reasons(found: list[Match], lang: str, limit: int = 5) -> str:
    """One line per matching account, e.g. "x@y.com: same phone, same IP"."""
    labels = REASON_LABELS["ar" if lang == "ar" else "en"]
    lines = [f"{m.email}: {', '.join(labels[SignalKind(k)] for k in m.kinds)}" for m in found[:limit]]
    if len(found) > limit:
        lines.append(f"+{len(found) - limit}")
    return "\n".join(lines)


async def needs_review(db: AsyncSession, found: list[Match]) -> bool:
    """Every signup when the admin's review setting is on; otherwise only likely duplicates (strong evidence)."""
    return (await credit_svc.platform_settings(db)).signup_review or any(m.strong for m in found)


async def approve(db: AsyncSession, user: User, admin_id: uuid.UUID) -> bool:
    """Approve (or re-admit) the account; starts the trial if the email is already confirmed. Caller holds the user
    row lock and commits. Returns False if it was already approved."""
    if user.approval_status == ApprovalStatus.APPROVED:
        return False
    was_rejected = user.approval_status == ApprovalStatus.REJECTED
    user.approval_status = ApprovalStatus.APPROVED
    user.reviewed_by, user.reviewed_at, user.review_note = admin_id, datetime.now(UTC), None
    if user.email_verified_at is not None:
        await accounts.start_owner_trials(db, user)
    if user.email_verified_at is not None:
        nxt = {
            "next_en": "Your free trial credits are in your account.",
            "next_ar": "نقاط التجربة المجانية أُضيفت لحسابك.",
        }
    else:
        nxt = {
            "next_en": "Confirm your email with the link we sent you and your free trial credits are added right away.",
            "next_ar": "أكّد بريدك من الرابط الذي أرسلناه لك، وتُضاف نقاط التجربة المجانية فوراً.",
        }
    await notify(db, "account_approved", users=[user], params={"readmitted": was_rejected, **nxt}, link="/app")
    return True


async def reject(db: AsyncSession, user: User, admin_id: uuid.UUID, reason: str) -> bool:
    """Reject the account: it can no longer sign in. Caller holds the user row lock and commits."""
    if user.approval_status == ApprovalStatus.REJECTED:
        return False
    user.approval_status = ApprovalStatus.REJECTED
    user.reviewed_by, user.reviewed_at, user.review_note = admin_id, datetime.now(UTC), reason
    # Email only: the user is signed out from now on, so the bell and Telegram would never be read.
    await notify(db, "account_rejected", users=[user], params={"reason": reason}, only_channels={"email"})
    return True


def signup_params(user: User, company: str, found: list[Match]) -> dict:
    return {
        "user_id": str(user.id),
        "email": user.email,
        "name": user.full_name,
        "company": company,
        "phone": user.phone or "—",
        "nationality": user.nationality or "—",
        "ip": user.signup_ip or "—",
        "matches": len(found),
        "reasons_ar": reasons(found, "ar"),
        "reasons_en": reasons(found, "en"),
    }


async def notify_signup(db: AsyncSession, user: User, company: str, found: list[Match]) -> None:
    """Tell the platform admins (bell + Telegram, with Approve / Reject buttons when it waits for review)."""
    params = signup_params(user, company, found)
    if user.approval_status != ApprovalStatus.PENDING:
        await notify(db, "admin_new_user", params=params, link=f"/app/admin?tab=users&user={user.id}")
        return
    kind = "admin_signup_suspicious" if found else "admin_signup_review"
    await notify(db, kind, params=params, link=f"/app/admin?tab=users&user={user.id}")
