from datetime import UTC, datetime

import httpx
from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.api.deps import DB, CurrentPrincipal, audit, require_role
from app.core.config import get_settings
from app.core.errors import AppError, Conflict, NotFound
from app.login_browser import internal_token
from app.models import ProviderConfiguration
from app.models.enums import ProviderStatus, Role
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
    return await svc.list_providers(db, p.workspace_id)


class SessionIn(BaseModel):
    storage_state: dict = Field(description="Playwright storage state captured after a manual login. Write-only.")


@router.get("/sessions")
async def list_sessions(p: CurrentPrincipal, db: DB) -> list[dict]:
    """Linked social accounts (status and today's page usage only; cookies are never returned)."""
    return await sessions.session_status(db, p.workspace_id)


@router.post("/sessions/{platform}", dependencies=[require_role(Role.ADMIN)])
async def save_session(platform: str, body: SessionIn, p: CurrentPrincipal, db: DB) -> dict:
    if platform not in sessions.SESSION_PLATFORMS:
        raise NotFound("Unsupported platform")
    try:
        await sessions.save_session(db, p.workspace_id, platform, body.storage_state)
    except ValueError as exc:
        raise AppError(str(exc)) from exc
    await audit(db, p, "session.connected", "provider", sessions.config_key(platform), {"platform": platform})
    await db.commit()
    return next(x for x in await sessions.session_status(db, p.workspace_id) if x["platform"] == platform)


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


@router.post("/sessions/{platform}/login/start", dependencies=[require_role(Role.ADMIN)])
async def start_login(platform: str, p: CurrentPrincipal) -> dict:
    """Open a real browser on the platform's login page; the dashboard shows it through noVNC."""
    if platform not in sessions.SESSION_PLATFORMS:
        raise NotFound("Unsupported platform")
    res = await _login_browser("/start", {"platform": platform})
    base = get_settings().login_browser_public_url.rstrip("/")
    viewer = f"{base}/vnc.html?autoconnect=1&resize=scale&reconnect=1&password={res['vnc_password']}"
    return {"platform": platform, "viewer_url": viewer}


@router.post("/sessions/{platform}/login/finish", dependencies=[require_role(Role.ADMIN)])
async def finish_login(platform: str, p: CurrentPrincipal, db: DB) -> dict:
    """Take the cookies from the login browser and store them (encrypted) as this platform's session."""
    res = await _login_browser("/capture")
    if res.get("platform") != platform:
        raise Conflict("The login browser is open for a different platform")
    try:
        await sessions.save_session(db, p.workspace_id, platform, res["storage_state"])
    except ValueError as exc:
        raise AppError(str(exc)) from exc
    await audit(db, p, "session.connected", "provider", sessions.config_key(platform), {"platform": platform})
    await db.commit()
    await _login_browser("/cancel")  # saved: close the login browser
    return next(x for x in await sessions.session_status(db, p.workspace_id) if x["platform"] == platform)


@router.post("/sessions/{platform}/login/cancel", dependencies=[require_role(Role.ADMIN)])
async def cancel_login(platform: str, p: CurrentPrincipal) -> dict:
    return await _login_browser("/cancel")


@router.delete("/sessions/{platform}", dependencies=[require_role(Role.ADMIN)])
async def delete_session(platform: str, p: CurrentPrincipal, db: DB) -> dict:
    if platform not in sessions.SESSION_PLATFORMS:
        raise NotFound("Unsupported platform")
    await sessions.delete_session(db, p.workspace_id, platform)
    await audit(db, p, "session.disconnected", "provider", sessions.config_key(platform), {"platform": platform})
    await db.commit()
    return {"platform": platform, "status": "not_connected"}


@router.put("/{key}", dependencies=[require_role(Role.ADMIN)])
async def update_provider(key: str, body: ProviderUpdate, p: CurrentPrincipal, db: DB) -> dict:
    if key not in KNOWN:
        raise NotFound("Unknown provider")
    cfg = await svc.get_config(db, p.workspace_id, key)
    if cfg is None:
        cfg = ProviderConfiguration(workspace_id=p.workspace_id, provider_key=key, settings={})
        db.add(cfg)
        await db.flush()
    if body.enabled is not None:
        cfg.enabled = body.enabled
    if body.settings is not None:
        allowed = {"rate_limit_per_minute", "monthly_budget_usd", "max_queries", "model"}
        cfg.settings = {**(cfg.settings or {}), **{k: v for k, v in body.settings.items() if k in allowed}}
    if body.credentials is not None:
        await svc.save_credentials(db, p.workspace_id, key, body.credentials)
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
    return next(x for x in await svc.list_providers(db, p.workspace_id) if x["key"] == key)


@router.post("/{key}/test", dependencies=[require_role(Role.ADMIN)])
async def test_provider(key: str, p: CurrentPrincipal, db: DB) -> dict:
    if key not in KNOWN:
        raise NotFound("Unknown provider")
    state: ProviderState
    if key in INTEGRATIONS:
        creds, _ = await svc.credentials_for(db, p.workspace_id, key)
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
            state = await svc.provider_state(db, p.workspace_id, key)
    else:
        provider = get_discovery_provider(key)
        ctx = await svc.build_context(db, p.workspace_id, key)
        state = await provider.test_connection(ctx)
    cfg = await svc.get_config(db, p.workspace_id, key)
    if cfg is None:
        cfg = ProviderConfiguration(workspace_id=p.workspace_id, provider_key=key, settings={})
        db.add(cfg)
    cfg.last_status = state.status.value
    cfg.last_error = None if state.status == ProviderStatus.CONNECTED else state.detail
    cfg.last_tested_at = datetime.now(UTC).isoformat()
    await audit(db, p, "provider.tested", "provider", key, {"status": state.status.value})
    await db.commit()
    return {"key": key, "status": state.status.value, "detail": state.detail}
