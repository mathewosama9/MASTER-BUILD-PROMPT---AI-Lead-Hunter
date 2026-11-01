"""Small fixed-window counters in Redis for endpoints that need a tighter limit than the global one."""

from app.core.errors import AppError
from app.core.redis import async_redis


class TooManyRequests(AppError):
    status_code = 429

    def __init__(self, message: str = "Too many requests; try again later") -> None:
        super().__init__(message, code="rate_limited")


async def enforce(key: str, limit: int, window_seconds: int) -> None:
    """Count one hit on `key`; raises TooManyRequests past `limit` per window. Fails closed without Redis."""
    try:
        r = async_redis()
        try:
            full = f"ratelimit:{key}"
            count = await r.incr(full)
            if count == 1:
                await r.expire(full, window_seconds)
        finally:
            await r.aclose()
    except Exception as exc:  # noqa: BLE001 - an uncounted endpoint is an unlimited one
        raise AppError("Temporarily unavailable; try again shortly", status_code=503) from exc
    if count > limit:
        raise TooManyRequests()
