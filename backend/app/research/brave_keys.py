"""Several Brave Search API keys in one credential, used in turn.

The credential value may hold many keys separated by commas, spaces or new lines. Requests start from the next
key in round-robin order; a key that is rate limited, out of quota or rejected rests for a while and the request
moves on to the next one. Cooldowns are kept per process, which is enough for one worker's run.
"""

import re
import time
from collections.abc import Awaitable, Callable
from itertools import count

import httpx

RATE_LIMIT_REST = 60.0  # seconds, when Brave sends no retry-after
QUOTA_REST = 3600.0  # 402: monthly/plan quota used up
REJECTED_REST = 6 * 3600.0  # 401/403: invalid or revoked key
ROTATE_ON = (401, 402, 403, 429)

_resting: dict[str, float] = {}
_turn = count()


def split_keys(value: str | None) -> list[str]:
    seen: dict[str, None] = {}
    for k in re.split(r"[\s,;]+", value or ""):
        if k:
            seen.setdefault(k, None)
    return list(seen)


def _numbers(raw: str | None) -> list[float]:
    try:
        return [float(v) for v in (raw or "").split(",") if v.strip()]
    except ValueError:
        return []


def _retry_after(resp: httpx.Response) -> float | None:
    """Seconds until the key works again. Brave sends one value per window ("1, 1419704" = per second, per
    month); rest until the longest window that is used up resets, so a key out of monthly quota waits a month."""
    if retry := _numbers(resp.headers.get("retry-after")):
        return retry[0]
    resets = _numbers(resp.headers.get("x-ratelimit-reset"))
    remaining = _numbers(resp.headers.get("x-ratelimit-remaining"))
    spent = [r for r, left in zip(resets, remaining, strict=False) if left <= 0]
    return max(spent or resets[:1], default=None)


def _rest_for(resp: httpx.Response) -> float:
    if resp.status_code == 429:
        return _retry_after(resp) or RATE_LIMIT_REST
    return QUOTA_REST if resp.status_code == 402 else REJECTED_REST


def _key_failed(resp: httpx.Response) -> bool:
    if resp.status_code in ROTATE_ON:
        return True
    # Brave answers an invalid/revoked key with 422 SUBSCRIPTION_TOKEN_INVALID
    return resp.status_code == 422 and "SUBSCRIPTION_TOKEN" in resp.text


def ordered(keys: list[str]) -> list[str]:
    """Keys in the order to try: rotated by one each call, resting keys last (still tried if all rest)."""
    if not keys:
        return []
    start = next(_turn) % len(keys)
    rotated = keys[start:] + keys[:start]
    now = time.monotonic()
    return [k for k in rotated if _resting.get(k, 0) <= now] + [k for k in rotated if _resting.get(k, 0) > now]


def rest(key: str, seconds: float) -> None:
    _resting[key] = time.monotonic() + seconds


async def get_with_rotation(keys_value: str, send: Callable[[str], Awaitable[httpx.Response]]) -> httpx.Response:
    """Call `send(key)` with each key until one is not rate limited/out of quota/rejected.
    Returns the last response when every key fails that way, so callers keep their own error handling."""
    keys = split_keys(keys_value)
    if not keys:
        return await send("")
    resp: httpx.Response | None = None
    for key in ordered(keys):
        resp = await send(key)
        if not _key_failed(resp):
            return resp
        rest(key, _rest_for(resp))
    assert resp is not None
    return resp
