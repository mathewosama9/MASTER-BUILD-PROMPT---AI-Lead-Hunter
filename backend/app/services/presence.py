"""When each user was last active, and on which browser, for the platform admin.

Sign-in only happens once per session, so every authenticated request calls `touch`. It writes at most once every
few minutes per user across all API processes: a small in-process cache answers most requests without any I/O, and a
Redis key (SET NX EX) stops the other processes from writing the same minute. The write runs as a detached task
after the request has its own connection back: at most MAX_WRITERS at a time per process, and dropped (it is only a
timestamp) when MAX_PENDING are already waiting, so a burst can never exhaust the database pool. It is two single-row
updates in their own short transaction and adds no rows.
"""

import asyncio
import logging
import re
import time
import uuid
from collections import OrderedDict
from datetime import UTC, datetime

import redis.asyncio as aioredis
from fastapi import Request
from sqlalchemy import update

from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.models import AccountSignal, User
from app.models.enums import SignalKind
from app.services import signup_review as review

log = logging.getLogger(__name__)
EVERY_SECONDS = 300
LOCAL_MAX = 50_000  # users remembered per process; the oldest are forgotten first
_DEVICE = re.compile(r"[a-f0-9]{32}")
_seen: OrderedDict[uuid.UUID, float] = OrderedDict()
_redis: dict[int, aioredis.Redis] = {}  # one pooled client per event loop
MAX_WRITERS = 4
MAX_PENDING = 500
_tasks: set[asyncio.Task] = set()
_slots: dict[int, asyncio.Semaphore] = {}


def _recently_seen(user_id: uuid.UUID, now: float) -> bool:
    last = _seen.get(user_id)
    if last is not None and now - last < EVERY_SECONDS:
        return True
    _seen[user_id] = now
    _seen.move_to_end(user_id)
    while len(_seen) > LOCAL_MAX:
        _seen.popitem(last=False)
    return False


def _client() -> aioredis.Redis:
    loop = id(asyncio.get_running_loop())
    client = _redis.get(loop)
    if client is None:
        client = _redis[loop] = aioredis.from_url(get_settings().redis_url, decode_responses=True)
    return client


async def _claim(user_id: uuid.UUID) -> bool:
    """True if this process should write now (no other process did in the last few minutes)."""
    try:
        return bool(await _client().set(f"presence:{user_id}", "1", nx=True, ex=EVERY_SECONDS))
    except Exception:  # noqa: BLE001 - without Redis the in-process cache still limits writes
        return True


async def touch(request: Request, user: User, via: str) -> None:
    """Never waits on I/O: either nothing to do, or the write is handed to a background task."""
    if len(_tasks) >= MAX_PENDING or _recently_seen(user.id, time.monotonic()):
        return
    ip = review.public_ip(request.client.host if request.client else None)
    device = request.cookies.get(review.DEVICE_COOKIE, "") if via == "web" else ""
    task = asyncio.create_task(_write(user.id, ip, device, request.headers.get("user-agent")))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def drain() -> None:
    """Wait for pending presence writes (tests, shutdown)."""
    while _tasks:
        await asyncio.gather(*list(_tasks), return_exceptions=True)


async def _write(user_id: uuid.UUID, ip: str | None, device: str, user_agent: str | None) -> None:
    slots = _slots.setdefault(id(asyncio.get_running_loop()), asyncio.Semaphore(MAX_WRITERS))
    async with slots:
        if not await _claim(user_id):
            return
        await _store(user_id, ip, device, user_agent)


async def _store(user_id: uuid.UUID, ip: str | None, device: str, user_agent: str | None) -> None:
    now = datetime.now(UTC)
    try:
        async with get_sessionmaker()() as db:
            await db.execute(
                update(User)
                .where(User.id == user_id)
                .values(last_seen_at=now, last_seen_ip=ip)
                .execution_options(synchronize_session=False)
            )
            if _DEVICE.fullmatch(device):
                # Keeps "last seen" fresh per browser between sign-ins; the row itself is created at sign-in.
                values: dict = {"last_seen_at": now}
                if ip:
                    values["ip"] = ip
                if user_agent:
                    values["user_agent"] = user_agent[:400]
                await db.execute(
                    update(AccountSignal)
                    .where(
                        AccountSignal.user_id == user_id,
                        AccountSignal.kind == SignalKind.DEVICE,
                        AccountSignal.value == device,
                    )
                    .values(**values)
                    .execution_options(synchronize_session=False)
                )
            await db.commit()
    except Exception:  # noqa: BLE001 - presence is best-effort and must never fail a request
        log.warning("recording presence failed", exc_info=True)
