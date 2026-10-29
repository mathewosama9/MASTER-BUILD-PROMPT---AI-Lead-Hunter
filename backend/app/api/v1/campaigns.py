import asyncio
import base64
import json
import uuid
from datetime import datetime

from fastapi import APIRouter, Query, Request
from sqlalchemy import func, or_, select
from sse_starlette.sse import EventSourceResponse

from app.api.deps import DB, CurrentPrincipal, audit, require_role
from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.core.errors import AppError, Conflict
from app.core.redis import async_redis
from app.models import Campaign, CampaignRun, CampaignSource, JobEvent
from app.models.enums import CampaignStatus, Role
from app.research.analysis.ai_service import AI_PROVIDERS, AIRefused, AIService, AIUnavailable
from app.research.analysis.heuristic import rule_based_spec
from app.research.providers.registry import get_discovery_provider
from app.schemas.campaign import (
    CampaignCreate,
    CampaignOut,
    CampaignUpdate,
    EstimateOut,
    EventOut,
    ImportPreviewIn,
    ImportPreviewOut,
    ParseSpecIn,
    RunOut,
)
from app.schemas.common import Message, Page
from app.services import campaigns as svc
from app.services import providers as provider_svc
from app.services.events import channel
from app.services.imports import ImportError_, encode_rows, parse_import

router = APIRouter(prefix="/campaigns", tags=["campaigns"])
SORTS = {"created_at": Campaign.created_at, "name": Campaign.name, "status": Campaign.status}


@router.get("", response_model=Page[CampaignOut])
async def list_campaigns(
    p: CurrentPrincipal,
    db: DB,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str | None = None,
    q: str | None = Query(None, max_length=100),
    is_demo: bool | None = None,
    sort: str = "created_at",
    order: str = Query("desc", pattern="^(asc|desc)$"),
) -> Page[CampaignOut]:
    stmt = select(Campaign).where(Campaign.workspace_id == p.workspace_id, Campaign.deleted_at.is_(None))
    if status:
        stmt = stmt.where(Campaign.status.in_(status.split(",")))
    if q:
        stmt = stmt.where(or_(Campaign.name.ilike(f"%{q}%"), Campaign.industry.ilike(f"%{q}%")))
    if is_demo is not None:
        stmt = stmt.where(Campaign.is_demo.is_(is_demo))
    if p.via == "telegram" and p.telegram_account:
        stmt = stmt.where(Campaign.created_by == p.user.id)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    col = SORTS.get(sort, Campaign.created_at)
    stmt = stmt.order_by(col.desc() if order == "desc" else col.asc()).offset((page - 1) * page_size).limit(page_size)
    items = (await db.scalars(stmt)).all()
    return Page(items=[CampaignOut.model_validate(c) for c in items], total=total or 0, page=page, page_size=page_size)


@router.post("", response_model=CampaignOut, status_code=201, dependencies=[require_role(Role.ANALYST)])
async def create_campaign(body: CampaignCreate, p: CurrentPrincipal, db: DB, request: Request) -> CampaignOut:
    chat_id = p.telegram_account.chat_id if p.telegram_account else None
    campaign = await svc.create_campaign(db, p.workspace_id, p.user.id, body, origin=p.via, telegram_chat_id=chat_id)
    await audit(
        db,
        p,
        "campaign.created",
        "campaign",
        campaign.id,
        {"name": campaign.name},
        request.client.host if request.client else None,
    )
    await db.commit()
    if body.start:
        await svc.start_campaign(db, campaign)
    await db.refresh(campaign)
    return CampaignOut.model_validate(campaign)


@router.post("/parse-spec", dependencies=[require_role(Role.ANALYST)])
async def parse_spec(body: ParseSpecIn, p: CurrentPrincipal, db: DB) -> dict:
    """Convert natural-language targeting into a structured research spec (AI when configured)."""
    creds = {}
    for key in AI_PROVIDERS:
        c, _ = await provider_svc.credentials_for(db, p.workspace_id, key)
        if c:
            creds[key] = c
    ai = AIService(creds)
    if ai.available:
        try:
            result = await ai.parse_research_spec(body.text)
            return {**result.output.model_dump(), "parser": result.provider, "cost_usd": result.cost_usd}
        except (AIUnavailable, AIRefused) as exc:
            return {**rule_based_spec(body.text), "warning": str(exc)}
    return rule_based_spec(body.text)


@router.post("/import-preview", response_model=ImportPreviewOut, dependencies=[require_role(Role.ANALYST)])
async def import_preview(body: ImportPreviewIn, p: CurrentPrincipal) -> ImportPreviewOut:
    """Validate an uploaded CSV/XLSX list. The client sends `encoded` back as the import source's rows."""
    try:
        content = base64.b64decode(body.content_base64, validate=True)
    except ValueError as exc:
        raise AppError("File content is not valid base64") from exc
    try:
        rows, rejected = parse_import(body.filename, content)
    except ImportError_ as exc:
        raise AppError(str(exc)) from exc
    return ImportPreviewOut(rows=rows, rejected=rejected, encoded=encode_rows(rows))


@router.post("/estimate", response_model=EstimateOut)
async def estimate(body: CampaignCreate, p: CurrentPrincipal, db: DB) -> EstimateOut:
    s = get_settings()
    providers: dict[str, dict] = {}
    notes: list[str] = []
    requests = 0
    cost = 0.0
    for src in body.sources:
        state = await provider_svc.provider_state(db, p.workspace_id, src.provider_key)
        providers[src.provider_key] = {"status": state.status.value, "detail": state.detail}
        if state.status.value != "connected" and src.provider_key not in ("manual", "facebook"):
            notes.append(f"{src.provider_key} is {state.status.value}; it will be skipped.")
            continue
        if src.provider_key == "brave":
            pages = max(1, body.settings.max_companies // 20)
            requests += pages * 4
            cost += pages * 4 * s.cost_brave_per_request
        elif src.provider_key == "hunter":
            requests += 1
            cost += s.cost_hunter_per_request
    if body.settings.ai_analysis and not (body.is_demo or any(x.provider_key == "demo" for x in body.sources)):
        per_lead = (6000 / 1e6 * s.cost_ai_input_per_mtok) + (1500 / 1e6 * s.cost_ai_output_per_mtok)
        cost += per_lead * body.settings.max_companies
        notes.append(f"AI analysis estimated at ~${per_lead:.3f} per company (rough).")
    if body.settings.email_verification:
        cost += body.settings.max_companies * 2 * s.cost_hunter_per_request
    notes.append(f"Hard budget cap: ${body.settings.max_budget_usd:.2f}.")
    return EstimateOut(providers=providers, estimated_requests=requests, estimated_cost_usd=round(cost, 3), notes=notes)


@router.get("/{campaign_id}", response_model=CampaignOut)
async def get_campaign(campaign_id: uuid.UUID, p: CurrentPrincipal, db: DB) -> CampaignOut:
    return CampaignOut.model_validate(await svc.get_campaign(db, p.workspace_id, campaign_id))


@router.patch("/{campaign_id}", response_model=CampaignOut, dependencies=[require_role(Role.ANALYST)])
async def update_campaign(campaign_id: uuid.UUID, body: CampaignUpdate, p: CurrentPrincipal, db: DB) -> CampaignOut:
    c = await svc.get_campaign(db, p.workspace_id, campaign_id)
    if c.status != CampaignStatus.DRAFT:
        raise Conflict("Only draft campaigns can be edited")
    data = body.model_dump(exclude_none=True, exclude={"sources", "settings"})
    for k, v in data.items():
        setattr(c, k, v)
    if body.settings is not None:
        c.settings = body.settings.model_dump()
    if body.sources is not None:
        c.sources = [
            CampaignSource(provider_key=s.provider_key, manual_urls=s.manual_urls)
            for s in body.sources
            if (s.provider_key == "demo") == c.is_demo
        ]
    await db.commit()
    await db.refresh(c)
    return CampaignOut.model_validate(c)


@router.delete("/{campaign_id}", response_model=Message, dependencies=[require_role(Role.ANALYST)])
async def delete_campaign(campaign_id: uuid.UUID, p: CurrentPrincipal, db: DB) -> Message:
    c = await svc.get_campaign(db, p.workspace_id, campaign_id)
    if c.status in (
        CampaignStatus.QUEUED,
        CampaignStatus.DISCOVERING,
        CampaignStatus.ENRICHING,
        CampaignStatus.ANALYZING,
    ):
        raise Conflict("Cancel the campaign before deleting it")
    from datetime import UTC

    c.deleted_at = datetime.now(UTC)
    await audit(db, p, "campaign.deleted", "campaign", c.id)
    await db.commit()
    return Message(message="Campaign deleted (businesses are kept in the leads database)")


def _action(name: str):  # noqa: ANN202
    async def handler(campaign_id: uuid.UUID, p: CurrentPrincipal, db: DB) -> CampaignOut:
        p.require(Role.ANALYST)
        c = await svc.get_campaign(db, p.workspace_id, campaign_id)
        if p.via == "telegram" and c.telegram_chat_id is None and p.telegram_account:
            c.telegram_chat_id = p.telegram_account.chat_id
        if name == "start":
            await svc.start_campaign(db, c)
        elif name == "pause":
            await svc.pause_campaign(db, c)
        elif name == "resume":
            await svc.resume_campaign(db, c)
        elif name == "cancel":
            await svc.cancel_campaign(db, c)
        elif name == "retry":
            await svc.retry_failures(db, c)
        elif name == "duplicate":
            c = await svc.duplicate_campaign(db, c, p.user.id)
        await audit(db, p, f"campaign.{name}", "campaign", c.id)
        await db.commit()
        await db.refresh(c)
        return CampaignOut.model_validate(c)

    handler.__name__ = f"{name}_campaign"
    return handler


for _name in ("start", "pause", "resume", "cancel", "retry", "duplicate"):
    router.add_api_route(
        f"/{{campaign_id}}/{_name}",
        _action(_name),
        methods=["POST"],
        response_model=CampaignOut,
        status_code=201 if _name == "duplicate" else 200,
        name=f"{_name}_campaign",
    )


@router.get("/{campaign_id}/runs", response_model=list[RunOut])
async def list_runs(campaign_id: uuid.UUID, p: CurrentPrincipal, db: DB) -> list[RunOut]:
    await svc.get_campaign(db, p.workspace_id, campaign_id)
    runs = await db.scalars(
        select(CampaignRun).where(CampaignRun.campaign_id == campaign_id).order_by(CampaignRun.run_number.desc())
    )
    return [RunOut.model_validate(r) for r in runs]


@router.get("/{campaign_id}/events/history", response_model=list[EventOut])
async def event_history(
    campaign_id: uuid.UUID,
    p: CurrentPrincipal,
    db: DB,
    since: datetime | None = None,
    limit: int = Query(100, ge=1, le=500),
) -> list[EventOut]:
    """Polling fallback for the live monitor."""
    await svc.get_campaign(db, p.workspace_id, campaign_id)
    stmt = select(JobEvent).where(JobEvent.campaign_id == campaign_id)
    if since:
        stmt = stmt.where(JobEvent.created_at > since)
        stmt = stmt.order_by(JobEvent.created_at.asc()).limit(limit)
        rows = list(await db.scalars(stmt))
    else:
        rows = list(await db.scalars(stmt.order_by(JobEvent.created_at.desc()).limit(limit)))
        rows.reverse()
    return [EventOut.model_validate(e) for e in rows]


@router.get("/{campaign_id}/events")
async def stream_events(campaign_id: uuid.UUID, p: CurrentPrincipal, db: DB, request: Request) -> EventSourceResponse:
    """Server-Sent Events: initial snapshot, then live events from Redis pub/sub, with heartbeats."""
    campaign = await svc.get_campaign(db, p.workspace_id, campaign_id)
    snapshot = CampaignOut.model_validate(campaign).model_dump(mode="json")

    async def gen():  # noqa: ANN202
        yield {"event": "snapshot", "data": json.dumps(snapshot, ensure_ascii=False)}
        try:
            r = async_redis()
            pubsub = r.pubsub()
            await pubsub.subscribe(channel(campaign_id))
        except Exception:  # noqa: BLE001 - client falls back to polling
            yield {"event": "error", "data": json.dumps({"message": "realtime unavailable; use polling"})}
            return
        try:
            idle = 0.0
            while not await request.is_disconnected():
                msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if msg and msg.get("type") == "message":
                    idle = 0.0
                    data = json.loads(msg["data"])
                    yield {"event": data.get("type", "event"), "data": msg["data"]}
                    if data.get("type") == "status" and data.get("status") in (
                        "completed",
                        "partially_completed",
                        "failed",
                        "cancelled",
                    ):
                        async with get_sessionmaker()() as s2:
                            fresh = await s2.get(Campaign, campaign_id)
                            await s2.refresh(fresh, attribute_names=["sources"])
                            yield {"event": "snapshot", "data": CampaignOut.model_validate(fresh).model_dump_json()}
                else:
                    idle += 1.0
                    if idle >= 15:
                        idle = 0.0
                        yield {"event": "ping", "data": "{}"}
                await asyncio.sleep(0)
        finally:
            await pubsub.unsubscribe(channel(campaign_id))
            await pubsub.aclose()
            await r.aclose()

    return EventSourceResponse(gen())


@router.get("/{campaign_id}/sources/status")
async def sources_status(campaign_id: uuid.UUID, p: CurrentPrincipal, db: DB) -> list[dict]:
    c = await svc.get_campaign(db, p.workspace_id, campaign_id)
    out = []
    for s in c.sources:
        info = get_discovery_provider(s.provider_key).info
        out.append(
            {
                "provider_key": s.provider_key,
                "name": info.name,
                "status": s.status,
                "results_count": s.results_count,
                "last_error": s.last_error,
            }
        )
    return out
