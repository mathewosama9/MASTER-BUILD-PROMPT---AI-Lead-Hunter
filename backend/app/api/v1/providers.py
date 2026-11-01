import json
import secrets
from datetime import UTC, datetime

import httpx
from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.api.deps import DB, CurrentPrincipal, SuperPrincipal, audit
from app.core.config import get_settings
from app.core.errors import AppError, Conflict, Forbidden, NotFound
from app.core.redis import async_redis
from app.login_browser import LOGIN_TIMEOUT, internal_token
from app.models import ProviderConfiguration
from app.models.enums import ProviderStatus
from app.research.analysis.ai_service import AI_PROVIDERS, AIService
from app.research.providers.base import ProviderState
from app.research.providers.registry import INTEGRATIONS, discovery_providers, get_discovery_provider
from app.research.scraping import sessions
from app.services import providers as svc

router = APIRouter(prefix="/providers", tags=["providers"])
KNOWN = {p.info.key for p in discovery_providers()} | set(INTEGRATIONS)


class ProviderUpdate(BaseModel):
    enabled: bool | None = None
    credentials: dict[str, str] | None = Field(default=None, description="Write-only. Empty string clears a field.")
    settings: dict | None = None


@router.get("")
async def list_providers(p: CurrentPrincipal, db: DB) -> list[dict]:
    """Platform admins get the full platform-wide view; customers get statuses only (for the campaign wizard)."""
    if p.user.is_superuser:
        return await svc.list_providers(db, None)
    return await svc.list_providers(db, p.workspace_id, public=True)


class SessionIn(BaseModel):
    storage_state: dict = Field(description="Playwright storage state captured after a manual login. Write-only.")


# Linked social accounts and API keys are platform-wide: stored with workspace_id NULL and managed by platform
# admins only. Customers never see or change them.
PLATFORM = None


@router.get("/sessions")
async def list_sessions(p: SuperPrincipal, db: DB) -> list[dict]:
    """Linked social accounts (status and today's page usage only; cookies are never returned)."""
    return await sessions.session_status(db, PLATFORM)


@router.post("/sessions/{platform}")
async def save_session(platform: str, body: SessionIn, p: SuperPrincipal, db: DB) -> dict:
    if platform not in sessions.SESSION_PLATFORMS:
        raise NotFound("Unsupported platform")
    try:
        await sessions.save_session(db, PLATFORM, platform, body.storage_state)
    except ValueError as exc:
        raise AppError(str(exc)) from exc
    await audit(db, p, "session.connected", "provider", sessions.config_key(platform), {"platform": platform})
    await db.commit()
    return next(x for x in await sessions.session_status(db, PLATFORM) if x["platform"] == platform)


async def _login_browser(path: str, body: dict | None = None) -> dict:
    s = get_settings()
    try:
        async with httpx.AsyncClient(base_url=s.login_browser_url, timeout=60) as c:
            r = await c.post(path, json=body or {}, headers={"X-Internal-Token": internal_token()})
    except httpx.HTTPError as exc:
        raise AppError(
            "The login browser service is not running (docker compose up -d login-browser)", status_code=503
        ) from exc
    if r.status_code >= 400:
        detail = r.json().get("detail") if r.headers.get("content-type", "").startswith("application/json") else None
        raise AppError(f"Login browser: {detail or r.status_code}", status_code=502 if r.status_code >= 500 else 409)
    return r.json()


# The login browser is one shared Chromium. Each login is bound to the (workspace, user) that started it through
# an opaque id kept in Redis and in the browser itself, so nobody else can capture its cookies or close it.
LOGIN_OWNER_KEY = "login-browser:owner"
REDIS_DOWN = "Login is unavailable right now (Redis is not reachable)"


def _owned_by(owner: dict, p: CurrentPrincipal) -> bool:
    return owner.get("workspace_id") == str(p.workspace_id) and owner.get("user_id") == str(p.user.id)


async def _claim_login(p: CurrentPrincipal, platform: str) -> str:
    """Reserve the login browser for the caller; refuses while another user's login is still in progress."""
    login_id = secrets.token_urlsafe(24)
    value = json.dumps(
        {"login_id": login_id, "workspace_id": str(p.workspace_id), "user_id": str(p.user.id), "platform": platform}
    )
    try:
        r = async_redis()
        try:
            if not await r.set(LOGIN_OWNER_KEY, value, nx=True, ex=LOGIN_TIMEOUT):
                current = json.loads(await r.get(LOGIN_OWNER_KEY) or "{}")
                if current and not _owned_by(current, p):
                    raise Conflict("The login browser is busy with another login. Try again in a few minutes.")
                await r.set(LOGIN_OWNER_KEY, value, ex=LOGIN_TIMEOUT)  # the caller restarts their own login
        finally:
            await r.aclose()
    except AppError:
        raise
    except Exception as exc:  # noqa: BLE001 - without the binding the login cannot be protected, so refuse it
        raise AppError(REDIS_DOWN, status_code=503) from exc
    return login_id


async def _owned_login(p: CurrentPrincipal) -> dict:
    """The caller's login in progress; refuses when there is none or it belongs to someone else."""
    try:
        r = async_redis()
        try:
            raw = await r.get(LOGIN_OWNER_KEY)
        finally:
            await r.aclose()
    except Exception as exc:  # noqa: BLE001
        raise AppError(REDIS_DOWN, status_code=503) from exc
    owner = json.loads(raw) if raw else None
    if not owner:
        raise Conflict("No login in progress")
    if not _owned_by(owner, p):
        raise Forbidden("This login was started by someone else")
    return owner


async def _release_login(login_id: str) -> None:
    """Drop the binding, but only while it is still this login's (a newer one may have replaced it)."""
    try:
        r = async_redis()
        try:
            raw = await r.get(LOGIN_OWNER_KEY)
            if raw and json.loads(raw).get("login_id") == login_id:
                await r.delete(LOGIN_OWNER_KEY)
        finally:
            await r.aclose()
    except Exception:  # noqa: BLE001, S110 - the key expires with the login anyway
        pass


@router.post("/sessions/{platform}/login/start")
async def start_login(platform: str, p: SuperPrincipal) -> dict:
    """Open a real browser on the platform's login page; the dashboard shows it through noVNC."""
    if platform not in sessions.SESSION_PLATFORMS:
        raise NotFound("Unsupported platform")
    login_id = await _claim_login(p, platform)
    try:
        res = await _login_browser("/start", {"platform": platform, "login_id": login_id})
    except AppError:
        await _release_login(login_id)
        raise
    base = get_settings().login_browser_public_url.rstrip("/")
    viewer = f"{base}/vnc.html?autoconnect=1&resize=scale&reconnect=1&password={res['vnc_password']}"
    return {"platform": platform, "viewer_url": viewer}


@router.post("/sessions/{platform}/login/finish")
async def finish_login(platform: str, p: SuperPrincipal, db: DB) -> dict:
    """Take the cookies from the caller's login browser and store them (encrypted) as this platform's session."""
    owner = await _owned_login(p)
    if owner.get("platform") != platform:
        raise Conflict("The login browser is open for a different platform")
    res = await _login_browser("/capture", {"login_id": owner["login_id"]})
    if res.get("platform") != platform:
        raise Conflict("The login browser is open for a different platform")
    try:
        await sessions.save_session(db, PLATFORM, platform, res["storage_state"])
    except ValueError as exc:
        raise AppError(str(exc)) from exc
    await audit(db, p, "session.connected", "provider", sessions.config_key(platform), {"platform": platform})
    await db.commit()
    await _login_browser("/cancel", {"login_id": owner["login_id"]})  # saved: close the login browser
    await _release_login(owner["login_id"])
    return next(x for x in await sessions.session_status(db, PLATFORM) if x["platform"] == platform)


@router.post("/sessions/{platform}/login/cancel")
async def cancel_login(platform: str, p: SuperPrincipal) -> dict:
    owner = await _owned_login(p)
    res = await _login_browser("/cancel", {"login_id": owner["login_id"]})
    await _release_login(owner["login_id"])
    return res


@router.delete("/sessions/{platform}")
async def delete_session(platform: str, p: SuperPrincipal, db: DB) -> dict:
    if platform not in sessions.SESSION_PLATFORMS:
        raise NotFound("Unsupported platform")
    await sessions.delete_session(db, PLATFORM, platform)
    await audit(db, p, "session.disconnected", "provider", sessions.config_key(platform), {"platform": platform})
    await db.commit()
    return {"platform": platform, "status": "not_connected"}


@router.put("/{key}")
async def update_provider(key: str, body: ProviderUpdate, p: SuperPrincipal, db: DB) -> dict:
    if key not in KNOWN:
        raise NotFound("Unknown provider")
    cfg = await svc.get_config(db, PLATFORM, key)
    if cfg is None:
        cfg = ProviderConfiguration(workspace_id=PLATFORM, provider_key=key, settings={})
        db.add(cfg)
        await db.flush()
    if body.enabled is not None:
        cfg.enabled = body.enabled
    if body.settings is not None:
        allowed = {"rate_limit_per_minute", "monthly_budget_usd", "max_queries", "model"}
        cfg.settings = {**(cfg.settings or {}), **{k: v for k, v in body.settings.items() if k in allowed}}
    if body.credentials is not None:
        await svc.save_credentials(db, PLATFORM, key, body.credentials)
    await audit(
        db,
        p,
        "provider.updated",
        "provider",
        key,
        {
            "enabled": body.enabled,
            "credential_fields": sorted((body.credentials or {}).keys()),
            "settings": body.settings,
        },
    )
    await db.commit()
    return next(x for x in await svc.list_providers(db, PLATFORM) if x["key"] == key)


@router.post("/{key}/test")
async def test_provider(key: str, p: SuperPrincipal, db: DB) -> dict:
    if key not in KNOWN:
        raise NotFound("Unknown provider")
    state: ProviderState
    if key in INTEGRATIONS:
        creds, _ = await svc.credentials_for(db, PLATFORM, key)
        if key in AI_PROVIDERS:
            ai = AIService({key: creds})
            if not ai.available:
                state = ProviderState(ProviderStatus.REQUIRES_API_KEY, "No API key configured")
            else:
                try:
                    from app.research.analysis.schemas import ResearchSpec

                    await ai.structured("Return a spec.", "Dental clinics in Riyadh", ResearchSpec)
                    state = ProviderState(ProviderStatus.CONNECTED, "Model responded with structured output.")
                except Exception as exc:  # noqa: BLE001 - surfaced to the admin
                    state = ProviderState(ProviderStatus.ERROR, f"{type(exc).__name__}: {str(exc)[:200]}")
        elif key == "telegram" and creds.get("bot_token"):
            import httpx

            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(f"https://api.telegram.org/bot{creds['bot_token']}/getMe")
            state = (
                ProviderState(ProviderStatus.CONNECTED, f"Bot @{r.json()['result']['username']}")
                if r.is_success
                else ProviderState(ProviderStatus.ERROR, "Telegram rejected the token")
            )
        else:
            state = await svc.provider_state(db, PLATFORM, key)
    else:
        provider = get_discovery_provider(key)
        ctx = await svc.build_context(db, PLATFORM, key)
        state = await provider.test_connection(ctx)
    cfg = await svc.get_config(db, PLATFORM, key)
    if cfg is None:
        cfg = ProviderConfiguration(workspace_id=PLATFORM, provider_key=key, settings={})
        db.add(cfg)
    cfg.last_status = state.status.value
    cfg.last_error = None if state.status == ProviderStatus.CONNECTED else state.detail
    cfg.last_tested_at = datetime.now(UTC).isoformat()
    await audit(db, p, "provider.tested", "provider", key, {"status": state.status.value})
    await db.commit()
    return {"key": key, "status": state.status.value, "detail": state.detail}
