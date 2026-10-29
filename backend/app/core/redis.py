import redis as syncredis
import redis.asyncio as aioredis

from app.core.config import get_settings


def async_redis() -> aioredis.Redis:
    return aioredis.from_url(get_settings().redis_url, decode_responses=True)


def sync_redis() -> syncredis.Redis:
    return syncredis.from_url(get_settings().redis_url, decode_responses=True)
