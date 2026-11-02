import httpx
import pytest

from app.core.crypto import mask_secret
from app.research import brave_keys


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.setattr(brave_keys, "_resting", {})


def test_split_keys_dedupes_and_accepts_separators():
    assert brave_keys.split_keys(" a,b\nc ; a ") == ["a", "b", "c"]
    assert brave_keys.split_keys(None) == []


async def test_rotates_past_limited_and_exhausted_keys():
    seen: list[str] = []

    async def send(key: str) -> httpx.Response:
        seen.append(key)
        return httpx.Response({"k1": 429, "k2": 402}.get(key, 200))

    for _ in range(3):  # whatever key the round-robin starts on, k3 answers
        resp = await brave_keys.get_with_rotation("k1,k2,k3", send)
        assert resp.status_code == 200
    # k1 and k2 now rest, so later calls go straight to k3
    seen.clear()
    await brave_keys.get_with_rotation("k1,k2,k3", send)
    assert seen == ["k3"]


async def test_returns_last_failure_when_all_keys_fail():
    async def send(key: str) -> httpx.Response:
        return httpx.Response(429)

    assert (await brave_keys.get_with_rotation("a,b", send)).status_code == 429


def test_mask_each_key():
    assert mask_secret("aaaaaaaaa1111,bbbbbbbbb2222") == "********1111, ********2222"


async def test_skips_key_brave_reports_invalid():
    async def send(key: str) -> httpx.Response:
        if key == "bad":
            return httpx.Response(422, json={"error": {"code": "SUBSCRIPTION_TOKEN_INVALID"}})
        return httpx.Response(200)

    for _ in range(2):
        assert (await brave_keys.get_with_rotation("bad,good", send)).status_code == 200


def test_key_out_of_monthly_quota_rests_until_month_resets():
    month = httpx.Response(429, headers={"x-ratelimit-remaining": "1, 0", "x-ratelimit-reset": "1, 1419704"})
    second = httpx.Response(429, headers={"x-ratelimit-remaining": "0, 900", "x-ratelimit-reset": "1, 1419704"})
    assert brave_keys._rest_for(month) == 1419704
    assert brave_keys._rest_for(second) == 1


async def test_exhausted_key_falls_over_to_next():
    calls: list[str] = []

    async def send(key: str) -> httpx.Response:
        calls.append(key)
        if key == "used-up":
            return httpx.Response(429, headers={"x-ratelimit-remaining": "1, 0", "x-ratelimit-reset": "1, 86400"})
        return httpx.Response(200)

    for _ in range(4):
        assert (await brave_keys.get_with_rotation("used-up,fresh", send)).status_code == 200
    assert calls.count("used-up") == 1  # tried once, then left resting
