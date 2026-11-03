import asyncio
import logging
import threading
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update

from app.core.config import get_settings
from app.core.db import worker_session
from app.core.redis import sync_redis
from app.models import Business
from app.research.pipeline import execute_campaign
from app.services.campaigns import stalled_runs
from app.workers.celery_app import celery_app

log = logging.getLogger(__name__)
# Runs have no time limit, so the run lock is kept short and renewed while the run is alive: a crashed worker
# frees it within LOCK_TTL, and a redelivered copy of a long run finds it held and exits.
LOCK_TTL = 60 * 15
LOCK_RENEW_EVERY = 60 * 5


def _keep_lock(lock, stop: threading.Event) -> None:  # noqa: ANN001
    while not stop.wait(LOCK_RENEW_EVERY):
        try:
            lock.extend(LOCK_TTL, replace_ttl=True)
        except Exception:  # noqa: BLE001 - lost the lock (Redis restart); the run itself carries on
            log.warning("run lock renewal failed")
            return


@celery_app.task(name="app.workers.tasks.run_campaign", bind=True, max_retries=3, acks_late=True)
def run_campaign(self, campaign_id: str, run_id: str) -> str | None:  # noqa: ANN001
    """Execute one campaign run. A Redis lock prevents two workers from running the same run concurrently."""
    # thread_local=False: the renewal thread must see this lock's token (redis-py keeps it per thread by default).
    lock = sync_redis().lock(f"lock:run:{run_id}", timeout=LOCK_TTL, blocking=False, thread_local=False)
    if not lock.acquire(blocking=False):
        log.info("run already executing elsewhere", extra={"run_id": run_id})
        return None
    stop = threading.Event()
    threading.Thread(target=_keep_lock, args=(lock, stop), daemon=True).start()
    try:
        return asyncio.run(_run(uuid.UUID(campaign_id), uuid.UUID(run_id)))
    except Exception as exc:
        log.exception("run_campaign crashed", extra={"run_id": run_id})
        raise self.retry(exc=exc, countdown=min(60 * 2**self.request.retries, 600)) from exc
    finally:
        stop.set()
        try:
            lock.release()
        except Exception:  # noqa: BLE001 - lock may already have expired
            log.debug("lock release skipped", extra={"run_id": run_id})


async def _run(campaign_id: uuid.UUID, run_id: uuid.UUID) -> str | None:
    async with worker_session() as db:
        status = await execute_campaign(db, campaign_id, run_id)
        return status.value if status else None


@celery_app.task(name="app.workers.tasks.recover_stalled_runs")
def recover_stalled_runs(stale_minutes: int = 10) -> int:
    return asyncio.run(_recover(stale_minutes))


async def _recover(stale_minutes: int) -> int:
    cutoff = datetime.now(UTC) - timedelta(minutes=stale_minutes)
    count = 0
    async with worker_session() as db:
        for run_id, campaign_id in await stalled_runs(db, cutoff):
            run_campaign.delay(str(campaign_id), str(run_id))
            count += 1
    if count:
        log.info("re-enqueued stalled runs", extra={"count": count})
    return count


@celery_app.task(name="app.workers.tasks.apply_retention")
def apply_retention() -> int:
    return asyncio.run(_retention())


async def _retention() -> int:
    """Soft-delete businesses not updated within the workspace retention window."""
    from app.models import Workspace

    total = 0
    async with worker_session() as db:
        for ws in (await db.scalars(select(Workspace).where(Workspace.deleted_at.is_(None)))).all():
            days = int((ws.settings or {}).get("retention_days") or get_settings().data_retention_days)
            cutoff = datetime.now(UTC) - timedelta(days=days)
            res = await db.execute(
                update(Business)
                .where(
                    Business.workspace_id == ws.id,
                    Business.deleted_at.is_(None),
                    Business.updated_at < cutoff,
                )
                .values(deleted_at=datetime.now(UTC))
            )
            total += res.rowcount or 0
        await db.commit()
    return total


@celery_app.task(name="app.workers.tasks.deliver_notifications")
def deliver_notifications() -> dict:
    """Send the queued emails and Telegram messages. One run at a time across workers: overlapping runs would
    each think they have the whole email allowance for the minute."""
    lock = sync_redis().lock("lock:notify-deliver", timeout=60 * 20, blocking=False)
    if not lock.acquire(blocking=False):
        return {"skipped": "another delivery run is active"}
    try:
        return asyncio.run(_deliver())
    finally:
        try:
            lock.release()
        except Exception:  # noqa: BLE001 - expired already
            log.debug("notify lock release skipped")


async def _deliver() -> dict:
    from app.services.notify.broadcast import resume_stale
    from app.services.notify.delivery import deliver_due

    async with worker_session() as db:
        await resume_stale(db)
        return await deliver_due(db)


@celery_app.task(name="app.workers.tasks.notification_daily_checks")
def notification_daily_checks() -> dict:
    return asyncio.run(_daily_checks())


async def _daily_checks() -> dict:
    from app.services.notify.scheduled import daily

    async with worker_session() as db:
        return await daily(db)
