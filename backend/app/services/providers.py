"""Provider configuration: credentials (env > encrypted DB), enable flags, status, usage and rate limits."""

import json
import logging
import time
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.crypto import decrypt_secret, encrypt_secret, mask_secret
from app.core.redis import async_redis
from app.models import Business, LeadAssessment, OutreachDraft, ProviderConfiguration, ProviderUsage
from app.models.enums import ProviderStatus
from app.research.providers.base import ProviderContext, ProviderInfo, ProviderState
from app.research.providers.registry import (
    INTEGRATIONS,
    credential_key,
    discovery_providers,
    env_credentials,
    get_discovery_provider,
)

log = logging.getLogger(__name__)


async def get_config(
    db: AsyncSession, workspace_id: uuid.UUID | None, key: str, *, fallback: bool = True
) -> ProviderConfiguration | None:
    """The workspace's own row if it has one, else the platform-wide row (`workspace_id=None` asks for that one)."""
    platform = ProviderConfiguration.workspace_id.is_(None)
    if workspace_id is not None:
        own = await db.scalar(
            select(ProviderConfiguration).where(
                ProviderConfiguration.workspace_id == workspace_id, ProviderConfiguration.provider_key == key
            )
        )
        if own is not None or not fallback:
            return own
    return await db.scalar(select(ProviderConfiguration).where(platform, ProviderConfiguration.provider_key == key))


async def record_outcome(
    db: AsyncSession, workspace_id: uuid.UUID, key: str, status: ProviderStatus, error: str | None = None
) -> None:
    """Keep the Settings status in step with real campaign runs, not only the last manual connection test."""
    cfg = await get_config(db, workspace_id, key)
    if cfg is None:
        return  # nothing stored yet, so nothing stale to correct
    cfg.last_status = status.value
    cfg.last_error = None if status == ProviderStatus.CONNECTED else (error or "")[:500] or None
    cfg.last_tested_at = datetime.now(UTC).isoformat()


async def credentials_for(
    db: AsyncSession, workspace_id: uuid.UUID | None, key: str
) -> tuple[dict[str, str], str | None]:
    """Return (credentials, source) where source is 'env', 'workspace', 'platform' or None."""
    env = env_credentials(key)
    if env:
        return env, "env"
    cfg = await get_config(db, workspace_id, credential_key(key))
    if cfg and cfg.encrypted_credentials:
        raw = decrypt_secret(cfg.encrypted_credentials)
        if raw:
            return json.loads(raw), ("platform" if cfg.workspace_id is None else "workspace")
    return {}, None


async def save_credentials(db: AsyncSession, workspace_id: uuid.UUID | None, key: str, creds: dict[str, str]) -> None:
    """Write to exactly the given scope (`None` = platform-wide), never to the row it would fall back to."""
    cfg = await get_config(db, workspace_id, key, fallback=False)
    if cfg is None:
        cfg = ProviderConfiguration(workspace_id=workspace_id, provider_key=key, settings={})
        db.add(cfg)
    existing = {}
    if cfg.encrypted_credentials:
        existing = json.loads(decrypt_secret(cfg.encrypted_credentials) or "{}")
    merged = {**existing, **{k: v for k, v in creds.items() if v}}
    for k, v in creds.items():
        if v == "":
            merged.pop(k, None)  # explicit clear
    cfg.encrypted_credentials = encrypt_secret(json.dumps(merged)) if merged else None
    await db.flush()


async def _rate_limited_until(key: str, workspace_id: uuid.UUID) -> float | None:
    try:
        r = async_redis()
        try:
            v = await r.get(f"ratelimited:{workspace_id}:{key}")
        finally:
            await r.aclose()
        return float(v) if v else None
    except Exception:  # noqa: BLE001 - status display only
        return None


async def mark_rate_limited(workspace_id: uuid.UUID, key: str, seconds: float) -> None:
    try:
        r = async_redis()
        try:
            until = str(time.time() + seconds)
            await r.set(f"ratelimited:{workspace_id}:{key}", until, ex=max(int(seconds), 1))
        finally:
            await r.aclose()
    except Exception as exc:  # noqa: BLE001 - rate-limit display is advisory
        log.debug("could not record rate limit", extra={"provider": key, "error": str(exc)[:120]})


async def build_context(
    db: AsyncSession, workspace_id: uuid.UUID, key: str, campaign_id: uuid.UUID | None = None
) -> ProviderContext:
    creds, _ = await credentials_for(db, workspace_id, key)
    cfg = await get_config(db, workspace_id, key)
    settings = dict(cfg.settings or {}) if cfg else {}
    settings["demo_mode"] = get_settings().demo_mode

    async def record(
        provider_key: str, operation: str, units: int, cost: float, success: bool, status_code: int | None
    ) -> None:
        db.add(
            ProviderUsage(
                workspace_id=workspace_id,
                campaign_id=campaign_id,
                provider_key=provider_key,
                operation=operation,
                units=units,
                cost_usd=cost,
                success=success,
                status_code=status_code,
            )
        )

    return ProviderContext(
        credentials=creds, settings=settings, record_usage=record, campaign_id=str(campaign_id) if campaign_id else None
    )


async def provider_state(db: AsyncSession, workspace_id: uuid.UUID, key: str) -> ProviderState:
    cfg = await get_config(db, workspace_id, key)
    if cfg is not None and not cfg.enabled:
        return ProviderState(ProviderStatus.DISABLED, "Disabled by an administrator.")
    until = await _rate_limited_until(key, workspace_id)
    if until and until > time.time():
        return ProviderState(ProviderStatus.RATE_LIMITED, f"Rate limited for {int(until - time.time())}s.")
    if key in INTEGRATIONS:
        creds, _ = await credentials_for(db, workspace_id, key)
        info = INTEGRATIONS[key]
        if all(creds.get(r) for r in info.requires):
            return ProviderState(ProviderStatus.CONNECTED)
        return ProviderState(ProviderStatus.REQUIRES_API_KEY, f"Missing: {', '.join(info.requires)}")
    provider = get_discovery_provider(key)
    ctx = await build_context(db, workspace_id, key)
    state = provider.state(ctx)
    # Credentials alone look "connected"; an account block seen in a real call or test (e.g. X credits
    # depleted) wins until a successful connection test or run clears it.
    if state.status == ProviderStatus.CONNECTED and cfg is not None and cfg.last_status == "requires_permission":
        return ProviderState(ProviderStatus.REQUIRES_PERMISSION, cfg.last_error or state.detail)
    return state


async def monthly_usage(db: AsyncSession, workspace_id: uuid.UUID | None) -> dict[str, dict]:
    """This month's requests and cost per provider; `None` = across all workspaces (platform admin view)."""
    start = datetime.now(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    scope = [] if workspace_id is None else [ProviderUsage.workspace_id == workspace_id]
    rows = await db.execute(
        select(ProviderUsage.provider_key, func.count(), func.coalesce(func.sum(ProviderUsage.cost_usd), 0.0))
        .where(*scope, ProviderUsage.created_at >= start)
        .group_by(ProviderUsage.provider_key)
    )
    usage: dict[str, list[float]] = {k: [int(n), float(c)] for k, n, c in rows.all()}
    # AI lead analyses and outreach drafts store their cost on their own rows, not in provider_usage.
    for model in (LeadAssessment, OutreachDraft):
        ai_rows = await db.execute(
            select(model.provider, func.count(), func.coalesce(func.sum(model.cost_usd), 0.0))
            .join(Business, Business.id == model.business_id)
            .where(
                *([] if workspace_id is None else [Business.workspace_id == workspace_id]), model.created_at >= start
            )
            .group_by(model.provider)
        )
        for k, n, c in ai_rows.all():
            cur = usage.setdefault(k, [0, 0.0])
            cur[0] += int(n)
            cur[1] += float(c)
    return {k: {"requests": int(n), "cost_usd": round(c, 4)} for k, (n, c) in usage.items()}


async def list_providers(db: AsyncSession, workspace_id: uuid.UUID | None, *, public: bool = False) -> list[dict]:
    """Every provider with its status. `public=True` (customers) keeps only what the campaign wizard needs:
    no credentials, costs, settings or error text."""
    usage = {} if public else await monthly_usage(db, workspace_id)
    out: list[dict] = []
    infos: list[ProviderInfo] = [p.info for p in discovery_providers()] + list(INTEGRATIONS.values())
    for info in infos:
        state = await provider_state(db, workspace_id, info.key)
        cfg = await get_config(db, workspace_id, info.key)
        if public:
            out.append(
                {
                    "key": info.key,
                    "name": info.name,
                    "kind": info.kind,
                    "description": "",
                    "requires": [],
                    "docs_url": None,
                    "status": state.status.value,
                    "status_detail": None,
                    "enabled": cfg.enabled if cfg else True,
                    "credential_source": None,
                    "credentials_masked": {},
                    "settings": {},
                    "last_tested_at": None,
                    "last_error": None,
                    "usage_month": {"requests": 0, "cost_usd": 0.0},
                }
            )
            continue
        creds, source = await credentials_for(db, workspace_id, info.key)
        out.append(
            {
                "key": info.key,
                "name": info.name,
                "kind": info.kind,
                "description": info.description,
                "requires": info.requires,
                "docs_url": info.docs_url,
                "status": state.status.value,
                "status_detail": state.detail,
                "enabled": cfg.enabled if cfg else True,
                "credential_source": source,
                "credentials_masked": {k: mask_secret(v) for k, v in creds.items()},
                "settings": (cfg.settings if cfg else {}) or {},
                "last_tested_at": cfg.last_tested_at if cfg else None,
                "last_error": cfg.last_error if cfg else None,
                "usage_month": usage.get(info.key, {"requests": 0, "cost_usd": 0.0}),
            }
        )
    return out
