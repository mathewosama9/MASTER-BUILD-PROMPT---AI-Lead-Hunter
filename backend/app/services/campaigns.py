"""Campaign lifecycle shared by the REST API (dashboard) and the Telegram bot."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import Conflict, NotFound
from app.models import Campaign, CampaignLead, CampaignRun, CampaignSource, Workspace
from app.models.enums import ACTIVE_STATUSES, CampaignStatus, Stage
from app.research.pipeline import DEFAULT_SETTINGS, start_new_run
from app.schemas.campaign import CampaignCreate
from app.services import credits as credit_svc
from app.services.events import emit, publish


def dispatch_run(campaign_id: uuid.UUID, run_id: uuid.UUID) -> str | None:
    """Enqueue the run on Celery. Patched in tests."""
    from app.workers.tasks import run_campaign

    result = run_campaign.apply_async(args=[str(campaign_id), str(run_id)], queue="research")
    return result.id


async def get_campaign(db: AsyncSession, workspace_id: uuid.UUID, campaign_id: uuid.UUID) -> Campaign:
    c = await db.scalar(
        select(Campaign).where(
            Campaign.id == campaign_id, Campaign.workspace_id == workspace_id, Campaign.deleted_at.is_(None)
        )
    )
    if c is None:
        raise NotFound("Campaign not found")
    return c


async def create_campaign(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
    data: CampaignCreate,
    origin: str = "web",
    telegram_chat_id: int | None = None,
) -> Campaign:
    is_demo = data.is_demo if data.is_demo is not None else any(s.provider_key == "demo" for s in data.sources)
    if is_demo and not get_settings().demo_mode:
        raise Conflict("Demo mode is disabled on this server")
    sources = data.sources
    if is_demo:
        sources = [s for s in sources if s.provider_key == "demo"] or [type(sources[0])(provider_key="demo")]
    else:
        sources = [s for s in sources if s.provider_key != "demo"]
        if not sources:
            raise Conflict("Select at least one real discovery source (the demo provider is for demo campaigns)")
    campaign = Campaign(
        workspace_id=workspace_id,
        created_by=user_id,
        name=data.name,
        status=CampaignStatus.DRAFT,
        origin=origin,
        is_demo=is_demo,
        country=data.country,
        city=data.city,
        region=data.region,
        language=data.language,
        industry=data.industry,
        keywords=data.keywords,
        excluded_keywords=data.excluded_keywords,
        company_size=data.company_size,
        characteristics=data.characteristics,
        services=data.services,
        nl_query=data.nl_query,
        research_spec=data.research_spec,
        settings=data.settings.model_dump(),
        stats={"target": data.settings.target_count},
        telegram_chat_id=telegram_chat_id,
    )
    campaign.sources = [CampaignSource(provider_key=s.provider_key, manual_urls=s.manual_urls) for s in sources]
    db.add(campaign)
    await db.flush()
    return campaign


async def ensure_can_run(db: AsyncSession, campaign: Campaign) -> None:
    """Paid runs need credits (and an unexpired trial while on trial). Demo campaigns are free."""
    if campaign.is_demo:
        return
    workspace = await db.get(Workspace, campaign.workspace_id)
    await db.refresh(workspace, attribute_names=["credit_balance", "trial_ends_at", "billing_exempt", "suspended_at"])
    await credit_svc.ensure_can_spend(db, workspace)


async def start_campaign(db: AsyncSession, campaign: Campaign) -> CampaignRun:
    if campaign.status in ACTIVE_STATUSES:
        raise Conflict("Campaign is already running")
    if campaign.status == CampaignStatus.PAUSED:
        raise Conflict("Campaign is paused; use resume")
    if campaign.status not in (CampaignStatus.DRAFT,):
        raise Conflict("Only draft campaigns can be started; duplicate or retry finished campaigns")
    await ensure_can_run(db, campaign)
    run = await start_new_run(db, campaign)
    campaign.status = CampaignStatus.QUEUED
    campaign.stage = Stage.CREATED.value
    await db.commit()
    await emit(
        db,
        campaign_id=campaign.id,
        run_id=run.id,
        stage="created",
        event_type="queued",
        message="Campaign queued",
        data={"t": "queued"},
    )
    run.celery_task_id = dispatch_run(campaign.id, run.id)
    await db.commit()
    return run


async def latest_run(db: AsyncSession, campaign_id: uuid.UUID) -> CampaignRun | None:
    return await db.scalar(
        select(CampaignRun)
        .where(CampaignRun.campaign_id == campaign_id)
        .order_by(CampaignRun.run_number.desc())
        .limit(1)
    )


async def pause_campaign(db: AsyncSession, campaign: Campaign) -> None:
    if campaign.status not in ACTIVE_STATUSES:
        raise Conflict("Only running campaigns can be paused")
    campaign.status = CampaignStatus.PAUSED
    await db.commit()
    run = await latest_run(db, campaign.id)
    await emit(
        db,
        campaign_id=campaign.id,
        run_id=run.id if run else None,
        stage=campaign.stage,
        event_type="pause_requested",
        message="Pause requested; the worker stops after the current step",
        data={"t": "pause_requested"},
    )
    await publish(campaign.id, {"type": "status", "status": "paused"})


async def resume_campaign(db: AsyncSession, campaign: Campaign) -> CampaignRun:
    if campaign.status != CampaignStatus.PAUSED:
        raise Conflict("Only paused campaigns can be resumed")
    await ensure_can_run(db, campaign)
    run = await latest_run(db, campaign.id)
    if run is None or run.finished_at is not None:
        run = await start_new_run(db, campaign)
    run.status = CampaignStatus.QUEUED
    campaign.status = CampaignStatus.QUEUED
    await db.commit()
    await emit(
        db,
        campaign_id=campaign.id,
        run_id=run.id,
        stage=campaign.stage,
        event_type="resumed",
        message="Campaign resumed from checkpoint",
        data={"t": "resumed"},
    )
    run.celery_task_id = dispatch_run(campaign.id, run.id)
    await db.commit()
    return run


async def cancel_campaign(db: AsyncSession, campaign: Campaign) -> None:
    if campaign.status not in (*ACTIVE_STATUSES, CampaignStatus.PAUSED, CampaignStatus.DRAFT):
        raise Conflict("Campaign has already finished")
    was_running = campaign.status in ACTIVE_STATUSES
    campaign.status = CampaignStatus.CANCELLED
    run = await latest_run(db, campaign.id)
    if not was_running:
        campaign.completed_at = datetime.now(UTC)
        if run and run.finished_at is None:
            run.status = CampaignStatus.CANCELLED
            run.finished_at = datetime.now(UTC)
    await db.commit()
    await emit(
        db,
        campaign_id=campaign.id,
        run_id=run.id if run else None,
        stage=campaign.stage,
        event_type="cancelled",
        message="Campaign cancelled; collected results are kept",
        data={"t": "cancelled"},
    )
    await publish(campaign.id, {"type": "status", "status": "cancelled"})


async def retry_failures(db: AsyncSession, campaign: Campaign) -> CampaignRun:
    """Start a new run that re-attempts failed/skipped sources and failed leads, keeping everything else."""
    if campaign.status not in (CampaignStatus.FAILED, CampaignStatus.PARTIALLY_COMPLETED, CampaignStatus.CANCELLED):
        raise Conflict("Only failed, partially completed or cancelled campaigns can be retried")
    await ensure_can_run(db, campaign)
    prev = await latest_run(db, campaign.id)
    for s in campaign.sources:
        if s.status in ("failed", "skipped", "running", "pending"):
            s.status = "pending"
            s.last_error = None
    await db.execute(
        update(CampaignLead)
        .where(CampaignLead.campaign_id == campaign.id, CampaignLead.processing_error.is_not(None))
        .values(processing_error=None, enriched=False, analyzed=False, scored=False)
    )
    run = await start_new_run(db, campaign)
    carried = {
        k: v
        for k, v in ((prev.checkpoint if prev else {}) or {}).items()
        if k in ("discovered", "duplicates_removed", "demo_profiles", "providers_succeeded")
    }
    run.checkpoint = carried
    campaign.status = CampaignStatus.QUEUED
    campaign.completed_at = None
    campaign.last_error = None
    await db.commit()
    await emit(
        db,
        campaign_id=campaign.id,
        run_id=run.id,
        stage="created",
        event_type="retry",
        message=f"Retry run #{run.run_number} queued",
        data={"t": "retry", "p": {"run": run.run_number}},
    )
    run.celery_task_id = dispatch_run(campaign.id, run.id)
    await db.commit()
    return run


async def duplicate_campaign(db: AsyncSession, campaign: Campaign, user_id: uuid.UUID) -> Campaign:
    copy = Campaign(
        workspace_id=campaign.workspace_id,
        created_by=user_id,
        name=f"{campaign.name} (copy)",
        status=CampaignStatus.DRAFT,
        origin=campaign.origin,
        is_demo=campaign.is_demo,
        country=campaign.country,
        city=campaign.city,
        region=campaign.region,
        language=campaign.language,
        industry=campaign.industry,
        keywords=list(campaign.keywords),
        excluded_keywords=list(campaign.excluded_keywords),
        company_size=campaign.company_size,
        characteristics=list(campaign.characteristics),
        services=list(campaign.services),
        nl_query=campaign.nl_query,
        research_spec=dict(campaign.research_spec),
        settings={**DEFAULT_SETTINGS, **campaign.settings},
        stats={"target": campaign.settings.get("target_count")},
    )
    copy.sources = [
        CampaignSource(provider_key=s.provider_key, manual_urls=list(s.manual_urls)) for s in campaign.sources
    ]
    db.add(copy)
    await db.flush()
    return copy
