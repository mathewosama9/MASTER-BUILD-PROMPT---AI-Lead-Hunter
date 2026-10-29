"""Logged-in browser sessions for social platforms, captured from the user's own (secondary) account.

The user logs in by hand in a real browser (`scripts/connect_session.py`); only the resulting cookies
(Playwright storage state) are stored, Fernet-encrypted like any other credential. Passwords never reach us.
Each platform has a small daily page cap, and a session that hits a login/checkpoint page is marked expired
and no longer used until the user reconnects it.
"""

import json
import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis import async_redis
from app.services import providers as provider_svc

log = logging.getLogger(__name__)

# platform -> (login URL, cookie domain that proves a login, default daily page cap)
SESSION_PLATFORMS: dict[str, tuple[str, str, int]] = {
    "linkedin": ("https://www.linkedin.com/login", "linkedin.com", 30),
    "tiktok": ("https://www.tiktok.com/login", "tiktok.com", 60),
    "snapchat": ("https://accounts.snapchat.com/accounts/login", "snapchat.com", 60),
    "instagram": ("https://www.instagram.com/accounts/login/", "instagram.com", 80),
    "facebook": ("https://www.facebook.com/login", "facebook.com", 80),
}
MAX_STATE_BYTES = 2_000_000
# Cookies that only exist after a successful login (anonymous visits also set cookies on these domains).
AUTH_COOKIES: dict[str, tuple[str, ...]] = {
    "linkedin": ("li_at",),
    "tiktok": ("sessionid", "sid_tt"),
    "snapchat": ("__Host-sc-a-auth-session", "sc-a-session"),
    "instagram": ("sessionid",),
    "facebook": ("c_user", "xs"),
}


class SessionExpired(Exception):
    def __init__(self, platform: str) -> None:
        super().__init__(f"{platform} session expired or the account was challenged; reconnect it in Settings")
        self.platform = platform


def config_key(platform: str) -> str:
    return f"session_{platform}"


def validate_state(platform: str, state: dict) -> dict:
    """Keep only cookies/origins for the platform's own domain; reject states without a login cookie."""
    if platform not in SESSION_PLATFORMS:
        raise ValueError("Unsupported platform")
    if len(json.dumps(state)) > MAX_STATE_BYTES:
        raise ValueError("Session data is too large")
    domain = SESSION_PLATFORMS[platform][1]
    cookies = [c for c in state.get("cookies", []) if isinstance(c, dict) and domain in str(c.get("domain", ""))]
    if not cookies:
        raise ValueError(f"No {domain} cookies found: log in fully before saving the session")
    names = {str(c.get("name", "")) for c in cookies}
    if not names & set(AUTH_COOKIES[platform]):
        raise ValueError(f"Not logged in to {platform} yet: finish the login (including 2FA), then save")
    origins = [o for o in state.get("origins", []) if isinstance(o, dict) and domain in str(o.get("origin", ""))]
    return {"cookies": cookies, "origins": origins}


async def save_session(db: AsyncSession, workspace_id: uuid.UUID, platform: str, state: dict) -> None:
    clean = validate_state(platform, state)
    await provider_svc.save_credentials(db, workspace_id, config_key(platform), {"storage_state": json.dumps(clean)})
    cfg = await provider_svc.get_config(db, workspace_id, config_key(platform))
    cfg.last_error = None
    cfg.last_tested_at = datetime.now(UTC).isoformat()  # stored as an ISO string (String column)
    cfg.enabled = True


async def delete_session(db: AsyncSession, workspace_id: uuid.UUID, platform: str) -> None:
    await provider_svc.save_credentials(db, workspace_id, config_key(platform), {"storage_state": ""})


async def mark_expired(db: AsyncSession, workspace_id: uuid.UUID, platform: str) -> None:
    cfg = await provider_svc.get_config(db, workspace_id, config_key(platform))
    if cfg is not None:
        cfg.last_error = "expired"


async def load_sessions(db: AsyncSession, workspace_id: uuid.UUID) -> dict[str, dict]:
    """Usable (connected, not expired) sessions: platform -> Playwright storage state."""
    out: dict[str, dict] = {}
    for platform in SESSION_PLATFORMS:
        cfg = await provider_svc.get_config(db, workspace_id, config_key(platform))
        if cfg is None or not cfg.enabled or cfg.last_error == "expired":
            continue
        creds, _ = await provider_svc.credentials_for(db, workspace_id, config_key(platform))
        if creds.get("storage_state"):
            try:
                out[platform] = json.loads(creds["storage_state"])
            except ValueError:
                log.warning("stored session is not valid JSON", extra={"platform": platform})
    return out


def _quota_key(workspace_id: uuid.UUID, platform: str) -> str:
    return f"session_pages:{workspace_id}:{platform}:{datetime.now(UTC):%Y%m%d}"


def daily_limit(platform: str, settings: dict | None = None) -> int:
    return int((settings or {}).get("daily_limit") or SESSION_PLATFORMS[platform][2])


async def take_quota(workspace_id: uuid.UUID, platform: str, limit: int) -> bool:
    """Count one logged-in page view; False once today's cap is reached (or Redis is unavailable)."""
    try:
        r = async_redis()
        try:
            key = _quota_key(workspace_id, platform)
            used = await r.incr(key)
            await r.expire(key, 60 * 60 * 48)
            return used <= limit
        finally:
            await r.aclose()
    except Exception as exc:  # noqa: BLE001 - without a counter we cannot enforce the cap, so do not use the session
        log.info("session quota unavailable", extra={"error": str(exc)[:120]})
        return False


async def used_today(workspace_id: uuid.UUID, platform: str) -> int | None:
    try:
        r = async_redis()
        try:
            v = await r.get(_quota_key(workspace_id, platform))
            return int(v) if v else 0
        finally:
            await r.aclose()
    except Exception:  # noqa: BLE001 - display only
        return None


async def session_status(db: AsyncSession, workspace_id: uuid.UUID) -> list[dict]:
    rows = []
    for platform, (login_url, _, _) in SESSION_PLATFORMS.items():
        cfg = await provider_svc.get_config(db, workspace_id, config_key(platform))
        creds, _ = await provider_svc.credentials_for(db, workspace_id, config_key(platform))
        connected = bool(creds.get("storage_state"))
        status = (
            "expired"
            if connected and cfg and cfg.last_error == "expired"
            else ("connected" if connected else "not_connected")
        )
        rows.append(
            {
                "platform": platform,
                "status": status,
                "connected_at": cfg.last_tested_at if cfg and connected else None,
                "daily_limit": daily_limit(platform, cfg.settings if cfg else None),
                "used_today": await used_today(workspace_id, platform) if connected else 0,
                "login_url": login_url,
            }
        )
    return rows
