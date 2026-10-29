"""Job events: persisted to `job_events` and fanned out over Redis pub/sub for SSE subscribers."""

import json
import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis import async_redis
from app.models import JobEvent

log = logging.getLogger(__name__)


def channel(campaign_id: uuid.UUID | str) -> str:
    return f"campaign:{campaign_id}:events"


async def publish(campaign_id: uuid.UUID | str, payload: dict) -> None:
    try:
        r = async_redis()
        try:
            await r.publish(channel(campaign_id), json.dumps(payload, default=str, ensure_ascii=False))
        finally:
            await r.aclose()
    except Exception as exc:  # noqa: BLE001 - realtime fan-out is best-effort; events are persisted anyway
        log.warning("event publish failed", extra={"campaign_id": str(campaign_id), "error": str(exc)[:200]})


async def emit(
    db: AsyncSession,
    *,
    campaign_id: uuid.UUID,
    run_id: uuid.UUID | None,
    stage: str,
    event_type: str,
    message: str,
    level: str = "info",
    provider_key: str | None = None,
    data: dict | None = None,
    commit: bool = True,
) -> JobEvent:
    event = JobEvent(
        campaign_id=campaign_id,
        run_id=run_id,
        stage=stage,
        event_type=event_type,
        message=message,
        level=level,
        provider_key=provider_key,
        data=data or {},
    )
    db.add(event)
    if commit:
        await db.commit()
    log.log(
        logging.WARNING if level in ("warning", "error") else logging.INFO,
        message,
        extra={"campaign_id": str(campaign_id), "stage": stage, "event_type": event_type, "provider": provider_key},
    )
    await publish(
        campaign_id,
        {
            "type": "event",
            "id": str(event.id),
            "stage": stage,
            "event_type": event_type,
            "message": message,
            "level": level,
            "provider_key": provider_key,
            "data": data or {},
            "created_at": event.created_at.isoformat() if event.created_at else None,
        },
    )
    return event
