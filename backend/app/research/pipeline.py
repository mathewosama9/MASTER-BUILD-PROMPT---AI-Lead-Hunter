"""Deterministic, observable research pipeline.

DISCOVERY -> NORMALIZATION -> DEDUPLICATION -> COMPANY/CONTACT ENRICHMENT -> AI ANALYSIS -> LEAD SCORING
-> PERSIST -> NOTIFY

Properties:
- Each stage records events, counters and a checkpoint on `campaign_runs` so a run can resume after a
  pause or a worker restart without redoing finished work (per-lead flags make every step idempotent).
- Results are committed incrementally, so a provider failure never loses already-collected data.
- Pause/cancel/budget/runtime are checked between work units.
- A failed provider is isolated: other providers continue; the campaign ends PARTIALLY_COMPLETED.
- No mock data ever replaces a failed real call. Demo data only comes from the explicit demo provider.
"""

import asyncio
import logging
import random
import time
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import (
    Business,
    BusinessContact,
    BusinessEvidence,
    BusinessSource,
    Campaign,
    CampaignLead,
    CampaignRun,
    CampaignSource,
    LeadAssessment,
    LeadScore,
    ProviderUsage,
    Workspace,
    WorkspaceProfile,
)
from app.models.enums import CampaignStatus, ContactType, Priority, ProviderStatus, Stage, VerificationStatus
from app.research import geo
from app.research.analysis.ai_service import AI_PROVIDERS, AIRefused, AIService, AIUnavailable
from app.research.analysis.heuristic import heuristic_analysis
from app.research.analysis.schemas import BusinessAnalysis
from app.research.catalog import decision_roles
from app.research.enrichment import people_finders
from app.research.enrichment.contacts import ContactFinding, classify_email, social_profile_url
from app.research.enrichment.decision_makers import (
    DecisionMaker,
    attach_known_emails,
    extract_with_ai,
    from_text,
    merge,
    search_linkedin,
    search_person_profiles,
)
from app.research.enrichment.dedupe import dedupe_candidates, find_existing_business
from app.research.enrichment.email_check import domain_accepts_mail
from app.research.enrichment.normalize import (
    business_domain,
    homepage_url,
    normalize_email,
    normalize_name,
    normalize_phone,
)
from app.research.enrichment.social_profiles import SUPPORTED as SOCIAL_PLATFORMS
from app.research.enrichment.social_profiles import contacts_in_bio, fetch_profile, platform_of
from app.research.enrichment.social_search import (
    NAME_ONLY_NOTE,
    SEARCH_PLATFORMS,
    SearchBlocked,
    best_match,
    build_query,
    web_search,
)
from app.research.enrichment.website import WebsiteResearch, research_website
from app.research.providers.base import (
    BusinessCandidate,
    ProviderError,
    RateLimited,
    SearchQuery,
)
from app.research.providers.demo import DemoSiteTransport
from app.research.providers.hunter import HunterClient
from app.research.providers.registry import get_discovery_provider
from app.research.scoring.scorer import ContactSummary, ScoringInput, score_lead
from app.research.scraping.browser import BrowserSession, BrowserUnavailable, PageSource
from app.research.scraping.parsers import ScrapeBlocked
from app.research.scraping.sessions import SessionExpired, daily_limit, load_sessions, mark_expired, take_quota
from app.services import credits as credit_svc
from app.services import providers as provider_svc
from app.services.events import emit, publish
from app.services.profile import seller_context
from app.services.suppression import contact_is_suppressed, suppression_sets

log = logging.getLogger(__name__)
PERSON_NOTE = "Named individual: treat as personal data; confirm a lawful basis before contacting."
# Contact rows that belong to a named decision maker (their own email/phone/WhatsApp/profile, not the business's).
PERSON_CHANNEL = "decision_maker"

DEFAULT_SETTINGS: dict[str, Any] = {
    "target_count": 20,
    "max_companies": 40,
    "max_pages_per_site": 8,
    "enrichment": True,
    "ai_analysis": True,
    "email_verification": False,
    "min_score": 50,
    "max_budget_usd": 5.0,
    "max_runtime_minutes": 30,
    "concurrency": 4,
    "exclude_duplicates": False,
}

MAX_PROVIDER_ATTEMPTS = 3
# Hygiene signals that say little about a service opportunity; excluded from evidence strength.
BASELINE_SIGNALS = {"https", "mobile_viewport", "english_content", "arabic_content"}
# Evidence captured outside the business website; kept when the website research is refreshed.
EXTERNAL_EVIDENCE_KINDS = ("listing", "social_profile")


def _identifiers(group: Any, phone: str | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in group.all:
        for k, v in item.identifiers.items():
            out.setdefault(k, v)
    if phone:
        out["phone"] = phone
    return out


class StopRun(Exception):
    """Raised to stop the run cleanly (pause, cancel, budget or runtime cap)."""

    def __init__(self, reason: str, status: CampaignStatus, code: str = "") -> None:
        super().__init__(reason)
        self.reason = reason
        self.status = status
        self.code = code  # stable key the UI translates (e.g. "max_budget")


def campaign_settings(campaign: Campaign) -> dict[str, Any]:
    return {**DEFAULT_SETTINGS, **(campaign.settings or {})}


class CampaignPipeline:
    def __init__(
        self,
        db: AsyncSession,
        campaign: Campaign,
        run: CampaignRun,
        *,
        site_transport: httpx.AsyncBaseTransport | None = None,
        page_source: PageSource | None = None,
        search_transport: httpx.AsyncBaseTransport | None = None,
        finder_transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.db = db
        self.finder_transport = finder_transport  # paid people finders (Hunter/Apollo/Lusha); tests mock it
        self.page_source = page_source
        self.search_transport = search_transport
        self._social_blocked = False
        self._search_blocked = False
        self._search_found = 0
        self._people_found = 0  # businesses whose decision maker was identified
        self._people_search_blocked = False
        self._named_off_noted = False
        self._ai_for_people: AIService | None | bool = False  # False = not built yet
        self._brave_key: str | None | bool = False  # False = not looked up yet
        self._roles: tuple[str, ...] | None = None
        self._finders: list[tuple[str, Any]] | None = None  # connected paid people finders, in order
        self._finder_off: set[str] = set()  # finders that failed for an account reason during this run
        self._person_search_blocked = False
        self._direct_found = 0  # decision makers delivered with a direct email/phone
        self._place: geo.Place | None = None  # where this campaign searches from (see geo.py)
        self.campaign = campaign
        self.run = run
        self.settings = campaign_settings(campaign)
        self.started = time.monotonic()
        self.site_transport = site_transport
        self.demo_profiles: dict[str, dict] = {}
        self.workspace: Workspace | None = None
        self.only_business: uuid.UUID | None = None  # re-analysis of a single lead
        self.partial_reasons: list[str] = list((run.checkpoint or {}).get("partial_reasons", []))
        self._last_progress_push = 0.0

    # ---------------------------------------------------------------- helpers

    @property
    def checkpoint(self) -> dict:
        return dict(self.run.checkpoint or {})

    def _set_checkpoint(self, **updates: Any) -> None:
        cp = self.checkpoint
        cp.update(updates)
        cp["partial_reasons"] = sorted(set(self.partial_reasons))
        self.run.checkpoint = cp

    def _stage_done(self, stage: Stage) -> bool:
        return stage.value in self.checkpoint.get("completed_stages", [])

    async def _complete_stage(self, stage: Stage) -> None:
        done = set(self.checkpoint.get("completed_stages", []))
        done.add(stage.value)
        self._set_checkpoint(completed_stages=sorted(done))
        await self.db.commit()

    async def event(
        self,
        stage: Stage | str,
        event_type: str,
        message: str,
        *,
        t: str | None = None,
        p: dict[str, Any] | None = None,
        **kw: Any,
    ) -> None:
        """`message` is the English log line; `t`/`p` let the UI render it in the user's language."""
        if t:
            kw["data"] = {**(kw.get("data") or {}), "t": t, "p": p or {}}
        await emit(
            self.db,
            campaign_id=self.campaign.id,
            run_id=self.run.id,
            stage=str(stage),
            event_type=event_type,
            message=message,
            **kw,
        )

    async def _set_status(self, status: CampaignStatus, stage: Stage) -> None:
        self.campaign.status = status
        self.campaign.stage = stage.value
        self.run.status = status
        self.run.stage = stage.value
        await self.db.commit()
        await self.push_progress(force=True)

    async def check_control(self) -> None:
        """Honour pause/cancel requests and budget/runtime caps between work units."""
        status = await self.db.scalar(select(Campaign.status).where(Campaign.id == self.campaign.id))
        if status == CampaignStatus.CANCELLED:
            raise StopRun("Cancelled by user", CampaignStatus.CANCELLED, "cancelled")
        if status == CampaignStatus.PAUSED:
            raise StopRun("Paused by user", CampaignStatus.PAUSED, "paused")
        elapsed_min = (time.monotonic() - self.started) / 60 + float(self.checkpoint.get("elapsed_minutes", 0))
        if elapsed_min > float(self.settings["max_runtime_minutes"]):
            raise StopRun("Maximum runtime reached", CampaignStatus.PARTIALLY_COMPLETED, "max_runtime")
        await self.check_budget()

    async def check_budget(self) -> None:
        await self._refresh_costs()
        if self.campaign.cost_discovery + self.campaign.cost_ai >= float(self.settings["max_budget_usd"]):
            raise StopRun("Maximum budget reached", CampaignStatus.PARTIALLY_COMPLETED, "max_budget")

    # ---------------------------------------------------------------- credits (see services/credits.py)

    async def _credits_per_contact(self) -> int:
        """0 when this run is not metered (demo campaign, exempt workspace or free contacts)."""
        if not hasattr(self, "_per_contact"):
            ws = self.workspace
            if self.campaign.is_demo or ws is None or ws.billing_exempt:
                self._per_contact = 0
            else:
                self._per_contact = max(0, (await credit_svc.platform_settings(self.db)).credits_per_contact)
        return self._per_contact

    async def _credit_room(self) -> int | None:
        """How many more new contacts the balance can pay for (None = unmetered). Stops the run at zero."""
        per = await self._credits_per_contact()
        if not per:
            return None
        balance = await self.db.scalar(select(Workspace.credit_balance).where(Workspace.id == self.workspace.id))
        room = int(balance or 0) // per
        if room <= 0:
            raise StopRun("Credits exhausted", CampaignStatus.PARTIALLY_COMPLETED, "credits_exhausted")
        return room

    async def _charge_lead(self, lead: CampaignLead, business: Business) -> None:
        """Charge once for a business new to the workspace delivered with a usable contact.

        If the balance ran out (e.g. another campaign spent it meanwhile) the lead is left unfinished, so a later
        run delivers and charges it, and the run stops.
        """
        per = await self._credits_per_contact()
        if not per or lead.pre_existing or lead.credits_charged:
            return
        if not await credit_svc.has_usable_contact(self.db, business.id):
            return
        try:
            await credit_svc.charge(
                self.db, self.workspace.id, per, campaign_id=self.campaign.id, business_id=business.id
            )
        except credit_svc.InsufficientCredits:
            raise StopRun("Credits exhausted", CampaignStatus.PARTIALLY_COMPLETED, "credits_exhausted") from None
        lead.credits_charged = per
        await self.db.commit()  # release the workspace row lock straight away

    async def _refresh_costs(self) -> None:
        await self.db.flush()
        usage = await self.db.scalar(
            select(func.coalesce(func.sum(ProviderUsage.cost_usd), 0.0)).where(
                ProviderUsage.campaign_id == self.campaign.id
            )
        )
        ai = await self.db.scalar(
            select(func.coalesce(func.sum(LeadAssessment.cost_usd), 0.0)).where(
                LeadAssessment.campaign_id == self.campaign.id
            )
        )
        self.campaign.cost_discovery = round(float(usage or 0.0), 4)
        self.campaign.cost_ai = round(float(ai or 0.0), 4)

    async def compute_stats(self) -> dict[str, Any]:
        cid = self.campaign.id
        leads = (
            await self.db.execute(
                select(
                    func.count(),
                    func.count().filter(CampaignLead.enriched),
                    func.count().filter(CampaignLead.analyzed),
                    func.count().filter(CampaignLead.scored),
                    func.count().filter(CampaignLead.qualified),
                    func.count().filter(CampaignLead.priority == Priority.HIGH),
                    func.count().filter(CampaignLead.processing_error.is_not(None)),
                ).where(CampaignLead.campaign_id == cid)
            )
        ).one()
        contact_rows = (
            await self.db.execute(
                select(BusinessContact.type, BusinessContact.verification_status, func.count())
                .join(CampaignLead, CampaignLead.business_id == BusinessContact.business_id)
                .where(CampaignLead.campaign_id == cid)
                .group_by(BusinessContact.type, BusinessContact.verification_status)
            )
        ).all()
        with_contacts = await self.db.scalar(
            select(func.count(func.distinct(BusinessContact.business_id)))
            .join(CampaignLead, CampaignLead.business_id == BusinessContact.business_id)
            .where(
                CampaignLead.campaign_id == cid,
                BusinessContact.type.in_([ContactType.EMAIL, ContactType.PHONE, ContactType.WHATSAPP]),
            )
        )
        emails = sum(n for t, _, n in contact_rows if t == ContactType.EMAIL)
        verified = sum(n for t, v, n in contact_rows if t == ContactType.EMAIL and v == VerificationStatus.VERIFIED)
        cp = self.checkpoint
        stats = {
            "target": int(self.settings["target_count"]),
            "discovered": int(cp.get("discovered", 0)),
            "duplicates_removed": int(cp.get("duplicates_removed", 0)),
            "unique_leads": leads[0],
            "enriched": leads[1],
            "analyzed": leads[2],
            "scored": leads[3],
            "qualified": leads[4],
            "high_priority": leads[5],
            "lead_errors": leads[6],
            "contacts_found": sum(n for _, _, n in contact_rows),
            "businesses_with_contacts": int(with_contacts or 0),
            "emails_found": emails,
            "verified_emails": verified,
            "rate_limit_warnings": int(cp.get("rate_limit_warnings", 0)),
            "provider_failures": int(cp.get("provider_failures", 0)),
            "ai_provider": cp.get("ai_provider"),
        }
        stats["progress"] = self._progress(stats)
        return stats

    def _progress(self, s: dict) -> dict:
        """Progress from measurable work units; `None` percent means indeterminate."""
        n = s["unique_leads"]
        if not self._stage_done(Stage.DEDUPLICATION):
            return {"percent": None, "completed_units": 0, "total_units": None}
        per_lead = 1 + int(bool(self.settings["enrichment"])) + int(bool(self.settings["ai_analysis"]))
        total = n * per_lead
        done = (
            s["scored"]
            + (s["enriched"] if self.settings["enrichment"] else 0)
            + (s["analyzed"] if self.settings["ai_analysis"] else 0)
        )
        pct = round(100 * done / total, 1) if total else 100.0
        return {"percent": pct, "completed_units": done, "total_units": total}

    async def push_progress(
        self,
        force: bool = False,
        activity: str | None = None,
        provider: str | None = None,
        activity_t: tuple[str, dict[str, Any]] | None = None,
    ) -> None:
        now = time.monotonic()
        if not force and now - self._last_progress_push < 1.0:
            return
        self._last_progress_push = now
        await self._refresh_costs()
        stats = await self.compute_stats()
        self.campaign.stats = stats
        self.run.counters = stats
        await self.db.commit()
        await publish(
            self.campaign.id,
            {
                "type": "progress",
                "status": self.campaign.status,
                "stage": self.campaign.stage,
                "stats": stats,
                "activity": activity,
                "activity_t": {"t": activity_t[0], "p": activity_t[1]} if activity_t else None,
                "provider": provider,
                "cost": {"discovery": self.campaign.cost_discovery, "ai": self.campaign.cost_ai},
            },
        )
        if self.campaign.telegram_chat_id:
            from app.services.notifications import telegram_progress

            try:
                await telegram_progress(self.db, self.campaign, force=False)
            except Exception:  # noqa: BLE001 - chat updates are best-effort
                log.warning("telegram progress update failed", exc_info=True)

    # ---------------------------------------------------------------- main

    async def execute(self) -> CampaignStatus:
        self.workspace = await self.db.get(Workspace, self.campaign.workspace_id)
        if self.run.started_at is None:
            self.run.started_at = datetime.now(UTC)
        if self.campaign.started_at is None:
            self.campaign.started_at = datetime.now(UTC)
        self.campaign.last_error = None
        await self.db.commit()
        await self.event(
            Stage.CREATED,
            "run_started",
            f"Run #{self.run.run_number} started" + (" (resumed)" if self.checkpoint else ""),
            t="run_resumed" if self.checkpoint else "run_started",
            p={"run": self.run.run_number},
        )
        final: CampaignStatus
        try:
            await self.check_control()
            if not self._stage_done(Stage.DISCOVERY):
                await self._set_status(CampaignStatus.DISCOVERING, Stage.DISCOVERY)
                candidates = await self.stage_discovery()
                await self.stage_persist_candidates(candidates)
            if self.settings["enrichment"] and not self._stage_done(Stage.CONTACT_ENRICHMENT):
                await self._set_status(CampaignStatus.ENRICHING, Stage.COMPANY_ENRICHMENT)
                await self.stage_enrichment()
            if self.settings["ai_analysis"] and not self._stage_done(Stage.AI_ANALYSIS):
                await self._set_status(CampaignStatus.ANALYZING, Stage.AI_ANALYSIS)
                await self.stage_analysis()
            if not self._stage_done(Stage.LEAD_SCORING):
                await self._set_status(CampaignStatus.ANALYZING, Stage.LEAD_SCORING)
                await self.stage_scoring()
            await self._complete_stage(Stage.PERSIST)
            final = CampaignStatus.PARTIALLY_COMPLETED if self.partial_reasons else CampaignStatus.COMPLETED
            stats = await self.compute_stats()
            if (
                stats["unique_leads"] == 0
                and self.checkpoint.get("provider_failures", 0)
                and not self.checkpoint.get("providers_succeeded")
            ):
                final = CampaignStatus.FAILED
                self.campaign.last_error = "All discovery providers failed."
        except StopRun as stop:
            final = stop.status
            if stop.status == CampaignStatus.PARTIALLY_COMPLETED:
                self.partial_reasons.append(stop.reason)
            await self.event(
                self.campaign.stage,
                "run_stopped",
                stop.reason,
                level="warning" if stop.status != CampaignStatus.PAUSED else "info",
                t=f"stop_{stop.code}" if stop.code else None,
            )
        except Exception as exc:
            log.exception("pipeline crashed")
            await self.db.rollback()
            final = CampaignStatus.FAILED
            self.campaign.last_error = f"{type(exc).__name__}: {exc}"[:1000]
            self.run.error = self.campaign.last_error
            await self.event(
                self.campaign.stage,
                "run_failed",
                f"Run failed: {self.campaign.last_error}",
                level="error",
                t="run_failed",
                p={"error": self.campaign.last_error},
            )

        elapsed = float(self.checkpoint.get("elapsed_minutes", 0)) + (time.monotonic() - self.started) / 60
        self._set_checkpoint(elapsed_minutes=round(elapsed, 3))
        if final == CampaignStatus.PAUSED:
            # The pause endpoint already set status; just persist the checkpoint.
            self.run.status = CampaignStatus.PAUSED
            await self.db.commit()
            await self.push_progress(force=True)
            return final
        if final == CampaignStatus.CANCELLED:
            self.run.status = CampaignStatus.CANCELLED
        else:
            self.campaign.status = final
            self.run.status = final
        self.campaign.stage = Stage.DONE.value
        self.run.stage = Stage.DONE.value
        now = datetime.now(UTC)
        self.run.finished_at = now
        self.campaign.completed_at = now
        if self.partial_reasons and final == CampaignStatus.PARTIALLY_COMPLETED:
            self.campaign.last_error = "; ".join(sorted(set(self.partial_reasons)))[:1000]
        await self.db.commit()
        await self.push_progress(force=True)
        await self.event(
            Stage.NOTIFY,
            "run_finished",
            f"Campaign finished with status {final.value}",
            data=self.campaign.stats,
            t="run_finished",
            p={"status": final.value},
        )
        await publish(self.campaign.id, {"type": "status", "status": final.value})
        return final

    # ---------------------------------------------------------------- stages

    def _query(self, source: CampaignSource) -> SearchQuery:
        c = self.campaign
        return SearchQuery(
            country=c.country,
            city=c.city,
            region=c.region,
            language=c.language,
            industry=c.industry,
            keywords=list(c.keywords or []),
            excluded_keywords=list(c.excluded_keywords or []),
            company_size=c.company_size,
            limit=int(self.settings["max_companies"]),
            manual_urls=list(source.manual_urls or []),
        )

    async def stage_discovery(self) -> list[BusinessCandidate]:
        all_candidates: list[BusinessCandidate] = []
        sources = sorted(self.campaign.sources, key=lambda s: s.provider_key)
        if not sources:
            raise StopRun("No discovery sources selected", CampaignStatus.FAILED, "no_sources")
        for source in sources:
            if source.status == "done":
                continue
            await self.check_control()
            key = source.provider_key
            try:
                provider = get_discovery_provider(key)
            except KeyError:
                source.status, source.last_error = "skipped", "Unknown provider"
                await self.event(
                    Stage.DISCOVERY,
                    "provider_skipped",
                    f"Unknown provider '{key}'",
                    level="warning",
                    provider_key=key,
                    t="unknown_provider",
                    p={"provider": key},
                )
                continue
            if self.campaign.is_demo != (key == "demo") and key not in ("manual",):
                source.status = "skipped"
                source.last_error = (
                    "Demo campaigns use only the demo provider"
                    if self.campaign.is_demo
                    else "The demo provider cannot be used in a real campaign"
                )
                await self.event(
                    Stage.DISCOVERY,
                    "provider_skipped",
                    source.last_error,
                    level="warning",
                    provider_key=key,
                    t="demo_only" if self.campaign.is_demo else "demo_not_allowed",
                )
                continue
            state = await provider_svc.provider_state(self.db, self.campaign.workspace_id, key)
            manual_ok = key in ("facebook", "manual") and source.manual_urls
            if state.status.value != "connected" and not manual_ok:
                source.status, source.last_error = "skipped", state.detail or state.status.value
                self.partial_reasons.append(f"{provider.info.name} unavailable ({state.status.value})")
                await self.event(
                    Stage.DISCOVERY,
                    "provider_unavailable",
                    f"{provider.info.name} skipped: {state.detail or state.status.value}",
                    level="warning",
                    provider_key=key,
                    t="provider_skipped",
                    p={"provider": key, "reason": state.status.value, "detail": state.detail},
                )
                await self.db.commit()
                continue
            source.status = "running"
            await self.db.commit()
            await self.event(
                Stage.DISCOVERY,
                "provider_started",
                f"Searching with {provider.info.name}",
                provider_key=key,
                t="provider_started",
                p={"provider": key},
            )
            await self.push_progress(
                force=True,
                activity=f"Searching {provider.info.name}",
                provider=key,
                activity_t=("searching", {"provider": key}),
            )
            ctx = await provider_svc.build_context(self.db, self.campaign.workspace_id, key, self.campaign.id)
            if self.campaign.is_demo:
                ctx.settings.update((self.campaign.research_spec or {}).get("demo_options", {}))
            try:
                query = self._query(source)
                found = await self._call_with_retries(key, lambda p=provider, q=query, c=ctx: p.search_businesses(q, c))
                source.status = "done"
                source.results_count = len(found)
                all_candidates.extend(found)
                self._set_checkpoint(providers_succeeded=True)
                if not self.campaign.is_demo:
                    await provider_svc.record_outcome(
                        self.db, self.campaign.workspace_id, key, ProviderStatus.CONNECTED
                    )
                await self.event(
                    Stage.DISCOVERY,
                    "provider_done",
                    f"{provider.info.name} returned {len(found)} businesses",
                    provider_key=key,
                    data={"count": len(found)},
                    t="provider_done",
                    p={"provider": key, "count": len(found)},
                )
            except ProviderError as exc:
                source.status, source.last_error = "failed", str(exc)[:500]
                self._set_checkpoint(provider_failures=int(self.checkpoint.get("provider_failures", 0)) + 1)
                self.partial_reasons.append(f"{provider.info.name} failed")
                if not self.campaign.is_demo:
                    # 402/403 are account problems (no credits, tier lacks access) that do not fix themselves.
                    blocked = exc.status_code in (402, 403)
                    await provider_svc.record_outcome(
                        self.db,
                        self.campaign.workspace_id,
                        key,
                        ProviderStatus.REQUIRES_PERMISSION if blocked else ProviderStatus.ERROR,
                        str(exc),
                    )
                await self.event(
                    Stage.DISCOVERY,
                    "provider_failed",
                    f"{provider.info.name} failed: {exc}",
                    level="error",
                    provider_key=key,
                    t="provider_failed",
                    p={"provider": key, "error": str(exc)},
                )
            await self.db.commit()
        self._set_checkpoint(discovered=int(self.checkpoint.get("discovered", 0)) + len(all_candidates))
        await self._complete_stage(Stage.DISCOVERY)
        return all_candidates

    async def _call_with_retries(self, key: str, fn: Any) -> Any:
        for attempt in range(1, MAX_PROVIDER_ATTEMPTS + 1):
            try:
                return await fn()
            except RateLimited as exc:
                self._set_checkpoint(rate_limit_warnings=int(self.checkpoint.get("rate_limit_warnings", 0)) + 1)
                wait = min(exc.retry_after or 2**attempt, 30.0)
                await provider_svc.mark_rate_limited(self.campaign.workspace_id, key, wait)
                await self.event(
                    Stage.DISCOVERY,
                    "rate_limited",
                    f"{key} rate limited (attempt {attempt}/{MAX_PROVIDER_ATTEMPTS}); waiting {wait:.1f}s",
                    level="warning",
                    provider_key=key,
                    t="rate_limited",
                    p={"provider": key, "attempt": attempt, "max": MAX_PROVIDER_ATTEMPTS, "wait": round(wait, 1)},
                )
                if attempt == MAX_PROVIDER_ATTEMPTS:
                    raise
                await asyncio.sleep(wait)
            except ProviderError as exc:
                if not exc.retryable or attempt == MAX_PROVIDER_ATTEMPTS:
                    raise
                await asyncio.sleep(min(2**attempt + random.random(), 20))
            except httpx.HTTPError as exc:
                if attempt == MAX_PROVIDER_ATTEMPTS:
                    raise ProviderError(f"Network error: {exc}") from exc
                await asyncio.sleep(min(2**attempt + random.random(), 20))
        raise ProviderError("unreachable")

    async def stage_persist_candidates(self, candidates: list[BusinessCandidate]) -> None:
        await self._set_status(CampaignStatus.DISCOVERING, Stage.NORMALIZATION)
        groups, removed_in_batch = dedupe_candidates(candidates)
        await self._complete_stage(Stage.NORMALIZATION)
        await self._set_status(CampaignStatus.DISCOVERING, Stage.DEDUPLICATION)
        removed = removed_in_batch
        max_companies = int(self.settings["max_companies"])
        existing_count = await self.db.scalar(select(func.count()).where(CampaignLead.campaign_id == self.campaign.id))
        added = int(existing_count or 0)
        excluded_existing = 0
        ws = self.campaign.workspace_id
        for group in groups:
            if added >= max_companies:
                break
            c = group.primary
            if c.is_demo != self.campaign.is_demo:
                continue
            business = None
            if not group.key.startswith("unkeyed:"):
                business = await find_existing_business(self.db, ws, group.key)
            pre_existing = business is not None
            if business is not None:
                already_linked = await self.db.scalar(
                    select(CampaignLead.id).where(
                        CampaignLead.campaign_id == self.campaign.id, CampaignLead.business_id == business.id
                    )
                )
                if already_linked:
                    removed += 1
                    continue
                if self.settings["exclude_duplicates"]:
                    excluded_existing += 1
                    removed += 1
                    continue
            if business is None:
                domain = business_domain(c.website_url)
                phone = normalize_phone(c.phone, c.country) if c.phone else None
                business = Business(
                    workspace_id=ws,
                    name=c.name,
                    normalized_name=normalize_name(c.name) or c.name.lower(),
                    website_url=c.website_url,
                    normalized_domain=domain,
                    identifiers=_identifiers(group, phone if not domain else None),
                    industry=c.industry,
                    country=c.country,
                    city=c.city,
                    address=c.address,
                    description=c.description,
                    is_demo=c.is_demo,
                    language=self.campaign.language,
                )
                self.db.add(business)
                await self.db.flush()
            else:
                business.description = business.description or c.description
                merged = {**_identifiers(group, None), **(business.identifiers or {})}
                if merged != (business.identifiers or {}):
                    business.identifiers = merged
            if not c.is_demo:
                await self._save_listing_contacts(business, group.all)
                await self._save_listing_evidence(business, group.all)
            for item in group.all:
                exists = await self.db.scalar(
                    select(BusinessSource.id).where(
                        BusinessSource.business_id == business.id,
                        BusinessSource.provider_key == item.source_provider,
                        BusinessSource.source_url == item.source_url,
                    )
                )
                if not exists:
                    self.db.add(
                        BusinessSource(
                            business_id=business.id,
                            campaign_id=self.campaign.id,
                            provider_key=item.source_provider,
                            source_url=item.source_url,
                            title=item.source_title,
                            snippet=item.description,
                            raw={k: v for k, v in item.raw.items() if k != "demo_profile"},
                            discovered_at=item.discovered_at,
                        )
                    )
            self.db.add(
                CampaignLead(
                    campaign_id=self.campaign.id,
                    business_id=business.id,
                    run_id=self.run.id,
                    discovered_via=c.source_provider,
                    pre_existing=pre_existing,
                )
            )
            if c.is_demo and "demo_profile" in c.raw:
                self._remember_demo(c.raw["demo_profile"])
            added += 1
            await self.db.commit()
        self._set_checkpoint(
            duplicates_removed=int(self.checkpoint.get("duplicates_removed", 0)) + removed,
            demo_profiles=list(self.demo_profiles.values()) or self.checkpoint.get("demo_profiles", []),
        )
        await self.event(
            Stage.DEDUPLICATION,
            "dedup_done",
            f"{added} unique businesses saved; {removed} duplicates removed"
            + (f" ({excluded_existing} already known to this workspace were excluded)" if excluded_existing else ""),
            data={"unique": added, "duplicates_removed": removed},
            t="dedup_done_excluded" if excluded_existing else "dedup_done",
            p={"unique": added, "removed": removed, "excluded": excluded_existing},
        )
        await self._complete_stage(Stage.DEDUPLICATION)
        await self.push_progress(force=True)

    async def _save_listing_contacts(self, business: Business, items: list[BusinessCandidate]) -> None:
        """Phone/email/social links published on the source listing itself (Maps, OSM, imported rows)."""
        sets = await self._suppression()
        for item in items:
            label = item.source_provider
            if item.phone:
                phone = normalize_phone(item.phone, item.country)
                if phone:
                    await self._upsert_contact(
                        business,
                        ContactFinding(
                            ContactType.PHONE,
                            phone,
                            phone,
                            item.source_url,
                            subtype="listing",
                            confidence=0.75,
                            source_provider=label,
                        ),
                        sets,
                    )
            if item.email:
                email = normalize_email(item.email)
                if email:
                    subtype, conf, restriction = classify_email(email, business.normalized_domain)
                    await self._upsert_contact(
                        business,
                        ContactFinding(
                            ContactType.EMAIL,
                            email,
                            email,
                            item.source_url,
                            subtype=subtype,
                            confidence=conf,
                            usage_restrictions=restriction,
                            source_provider=label,
                        ),
                        sets,
                    )
            for url in item.social_urls:
                platform, canon = social_profile_url(url)
                if platform:
                    await self._upsert_contact(
                        business,
                        ContactFinding(
                            ContactType.SOCIAL,
                            canon,
                            canon.lower(),
                            item.source_url,
                            subtype=platform,
                            confidence=0.7,
                            source_provider=label,
                        ),
                        sets,
                    )

    async def _save_listing_evidence(self, business: Business, items: list[BusinessCandidate]) -> None:
        """Facts shown on a map listing (rating, reviews, category, hours) as citable evidence."""
        for item in items:
            if item.source_provider not in ("google_maps", "osm"):
                continue
            raw = item.raw
            parts = []
            if raw.get("rating") is not None:
                reviews = f" ({raw['reviews']:,} reviews)" if raw.get("reviews") else ""
                parts.append(f"Rating {raw['rating']}{reviews}")
            if raw.get("category"):
                parts.append(f"Category: {raw['category']}")
            hours = raw.get("hours") or raw.get("opening_hours")
            if hours:
                parts.append(f"Hours: {hours}")
            if not parts:
                continue
            await self.db.execute(
                delete(BusinessEvidence).where(
                    BusinessEvidence.business_id == business.id,
                    BusinessEvidence.kind == "listing",
                    BusinessEvidence.url == item.source_url,
                )
            )
            label = "Google Maps" if item.source_provider == "google_maps" else "OpenStreetMap"
            self.db.add(
                BusinessEvidence(
                    business_id=business.id,
                    kind="listing",
                    signal_key=f"listing:{item.source_provider}",
                    url=item.source_url,
                    title=f"{label} listing",
                    excerpt=" · ".join(parts)[:2000],
                    observed=True,
                    captured_at=datetime.now(UTC),
                )
            )

    async def _suppression(self) -> dict[str, set[str]]:
        if not hasattr(self, "_sets_cache"):
            self._sets_cache = await suppression_sets(self.db, self.campaign.workspace_id)
        return self._sets_cache

    def _remember_demo(self, profile: dict) -> None:
        self.demo_profiles[profile["domain"]] = profile

    def _site_transport(self) -> httpx.AsyncBaseTransport | None:
        if self.site_transport is not None:
            return self.site_transport
        if self.campaign.is_demo:
            if not self.demo_profiles:
                for p in self.checkpoint.get("demo_profiles", []):
                    self._remember_demo(p)
            return DemoSiteTransport(self.demo_profiles, self.campaign.country)
        return None

    async def _pending_leads(self, flag: str) -> list[tuple[CampaignLead, Business]]:
        col = getattr(CampaignLead, flag)
        q = (
            select(CampaignLead, Business)
            .join(Business, Business.id == CampaignLead.business_id)
            .where(CampaignLead.campaign_id == self.campaign.id, col.is_(False))
            .order_by(CampaignLead.created_at)
        )
        if self.only_business is not None:
            q = q.where(Business.id == self.only_business)
        return list((await self.db.execute(q)).all())

    async def stage_enrichment(self) -> None:
        leads = await self._pending_leads("enriched")
        transport = self._site_transport()
        conc = max(1, min(int(self.settings["concurrency"]), 10))
        hunter_ctx = None
        if not self.campaign.is_demo:
            state = await provider_svc.provider_state(self.db, self.campaign.workspace_id, "hunter")
            if state.status.value == "connected":
                hunter_ctx = await provider_svc.build_context(
                    self.db, self.campaign.workspace_id, "hunter", self.campaign.id
                )
            elif self.settings["email_verification"]:
                self.partial_reasons.append("Email verification unavailable (Hunter not connected)")
                await self.event(
                    Stage.CONTACT_ENRICHMENT,
                    "provider_unavailable",
                    "Email verification requested but Hunter is not connected; emails stay unverified.",
                    level="warning",
                    provider_key="hunter",
                    t="hunter_not_connected",
                )
        sets = await suppression_sets(self.db, self.campaign.workspace_id)
        if not self.campaign.is_demo:
            await self._target_roles()  # before the concurrent website visits, which read it
            self._place = await geo.locate(self.campaign.country, self.campaign.city, self.campaign.region)
        social = await self._social_source()
        try:
            await self._enrich_batches(leads, conc, transport, hunter_ctx, sets, social)
        finally:
            if social is not None and social is not self.page_source:
                await social.close()
        await self._complete_stage(Stage.COMPANY_ENRICHMENT)
        await self._complete_stage(Stage.CONTACT_ENRICHMENT)
        if self._people_found:
            await self.event(
                Stage.CONTACT_ENRICHMENT,
                "decision_makers_done",
                f"Decision maker identified for {self._people_found} businesses "
                f"({self._direct_found} with a direct email/phone)",
                t="decision_makers_done",
                p={"count": self._people_found, "direct": self._direct_found},
            )
        if self._search_found:
            await self.event(
                Stage.CONTACT_ENRICHMENT,
                "social_search_done",
                f"Search by name found {self._search_found} social profiles",
                t="social_search_done",
                p={"count": self._search_found},
            )
        await self.event(
            Stage.CONTACT_ENRICHMENT, "stage_done", "Company and contact enrichment completed", t="enrichment_done"
        )
        await self.push_progress(force=True)

    async def _social_source(self) -> PageSource | None:
        s = get_settings()
        if self.campaign.is_demo or not (s.scraping_enabled and s.social_enrichment_enabled):
            return None
        self._sessions = await load_sessions(self.db, self.campaign.workspace_id)
        if self.page_source is not None:
            return self.page_source
        return BrowserSession(self.campaign.country, sessions=self._sessions, place=self._place)

    async def _use_session(self, platform: str | None) -> bool:
        """Whether this profile visit should go through the user's linked account (within today's cap)."""
        sessions = getattr(self, "_sessions", {})
        if not platform or platform not in sessions:
            return False
        if await take_quota(self.campaign.workspace_id, platform, daily_limit(platform)):
            return True
        if platform not in self.__dict__.setdefault("_quota_warned", set()):
            self._quota_warned.add(platform)
            await self.event(
                Stage.CONTACT_ENRICHMENT,
                "session_quota",
                f"Daily {platform} page limit for the linked account reached; continuing logged out.",
                level="warning",
                t="session_quota",
                p={"platform": platform},
            )
        return False

    async def _enrich_batches(
        self,
        leads: list[tuple[CampaignLead, Business]],
        conc: int,
        transport: httpx.AsyncBaseTransport | None,
        hunter_ctx: Any,
        sets: dict[str, set[str]],
        social: PageSource | None,
    ) -> None:
        i = 0
        while i < len(leads):
            await self.check_control()
            room = await self._credit_room()  # never research more new leads than the balance can pay for
            size = conc if room is None else min(conc, room)
            batch = leads[i : i + size]
            i += size
            await self.push_progress(
                activity=f"Researching {batch[0][1].name}",
                provider="website",
                activity_t=("researching", {"name": batch[0][1].name}),
            )
            results = await asyncio.gather(*[self._research(b, transport) for _, b in batch], return_exceptions=True)
            for (lead, business), res in zip(batch, results, strict=True):
                if isinstance(res, BaseException):
                    lead.processing_error = f"enrichment: {type(res).__name__}: {res}"[:500]
                    await self._charge_lead(lead, business)  # listing contacts are still delivered
                    lead.enriched = True
                    await self.event(
                        Stage.COMPANY_ENRICHMENT,
                        "lead_failed",
                        f"Could not research {business.name}: {res}",
                        level="warning",
                        t="research_failed",
                        p={"name": business.name, "error": str(res)},
                    )
                    continue
                await self._save_research(business, res, sets)
                if social is not None and not self._social_blocked:
                    # After the website visit, so profiles linked from the site are known too.
                    await self.push_progress(
                        activity=f"Social profiles of {business.name}",
                        provider="social",
                        activity_t=("social_profiles", {"name": business.name}),
                    )
                    had_website = bool(business.website_url)
                    await self._social_search(business, sets)
                    await self._social_enrich(business, social, sets)
                    if not had_website and business.website_url:  # website adopted from the business's own profile
                        try:
                            await self._save_research(business, await self._research(business, transport), sets)
                        except Exception as exc:  # noqa: BLE001 - keep the lead; record why the site was not read
                            lead.processing_error = f"enrichment: {type(exc).__name__}: {exc}"[:500]
                named = await self._decision_makers(business, res, sets)
                if hunter_ctx is not None and business.normalized_domain:
                    # Paid lookups only for leads the free sources could not name a decision maker for.
                    await self._hunter_enrich(business, hunter_ctx, sets, search=not named)
                elif self.campaign.is_demo and self.settings["email_verification"]:
                    await self._demo_verify(business)
                if not self.campaign.is_demo and get_settings().email_mx_check:
                    await self._mx_check(business)
                await self._refresh_contact_flags(business)
                await self._charge_lead(lead, business)
                lead.enriched = True
            await self.db.commit()

    async def _people_ai(self) -> AIService | None:
        if self._ai_for_people is False:
            creds = {}
            for key in AI_PROVIDERS:
                state = await provider_svc.provider_state(self.db, self.campaign.workspace_id, key)
                if state.status == ProviderStatus.CONNECTED:
                    creds[key] = (await provider_svc.credentials_for(self.db, self.campaign.workspace_id, key))[0]
            ai = AIService(creds)
            self._ai_for_people = ai if ai.available else None
        return self._ai_for_people or None

    def _record_usage(self, provider_key: str, operation: str, cost: float, units: int = 1) -> None:
        self.db.add(
            ProviderUsage(
                workspace_id=self.campaign.workspace_id,
                campaign_id=self.campaign.id,
                provider_key=provider_key,
                operation=operation,
                units=units,
                cost_usd=cost * units,
                success=True,
                status_code=200,
            )
        )

    async def _target_roles(self) -> tuple[str, ...]:
        """Who to reach at each prospect: roles the campaign asked for, who buys what this workspace sells,
        and who runs the prospect's kind of business (owners/founders/CEOs are always looked for too)."""
        if self._roles is None:
            spec = self.campaign.research_spec or {}
            category = await self.db.scalar(
                select(WorkspaceProfile.business_category).where(
                    WorkspaceProfile.workspace_id == self.campaign.workspace_id
                )
            )
            extra = [str(r) for r in spec.get("decision_roles") or [] if r]
            self._roles = tuple(decision_roles(self.campaign.industry, category, extra))
        return self._roles

    async def _decision_makers(
        self, business: Business, res: WebsiteResearch | None, sets: dict[str, set[str]]
    ) -> bool:
        """Name who decides at the business and find how to reach that person directly. Always on.

        Order (cheapest and most certain first): the site's schema.org data, team/about pages and the contacts
        printed next to each name; social bios; addresses already found that carry the person's name; LinkedIn
        results via Brave when nobody is named; then the person's own public accounts via Brave; finally the
        paid people finders (Hunter -> Apollo -> Lusha) only while the decision maker has no direct channel."""
        if self.campaign.is_demo:
            return False
        roles = await self._target_roles()
        people = list(res.people) if res is not None else []
        pages = [(p.url, p.excerpt) for p in (res.pages if res is not None else []) if p.kind in ("about", "team")]
        if pages and not any(p.source == "structured_data" for p in people):
            ai = await self._people_ai()
            if ai is not None:
                try:
                    found, cost = await extract_with_ai(ai, business.name, pages)
                    people += found
                    self._record_usage(ai.provider or "ai", "decision_makers", cost)
                except Exception as exc:  # noqa: BLE001 - the regex/structured results still stand
                    log.info("decision-maker AI extraction failed", extra={"error": str(exc)[:200]})
        bios = await self.db.execute(
            select(BusinessEvidence.url, BusinessEvidence.excerpt, BusinessEvidence.signal_key).where(
                BusinessEvidence.business_id == business.id,
                BusinessEvidence.kind == "social_profile",
                BusinessEvidence.observed.is_(True),
            )
        )
        for url, excerpt, signal_key in bios.all():
            platform = (signal_key or "social:social").split(":", 1)[1]
            people += from_text(excerpt or "", url or "", platform, confidence=0.45, extra_roles=roles)
        if not people:
            people = await self._linkedin_people(business, roles)
        if not people and business.normalized_domain:
            people = await self._apollo_people(business, roles)
        merged = merge(people, roles)[:3]
        if not merged:
            return False
        emails = (
            await self.db.execute(
                select(BusinessContact.normalized_value, BusinessContact.source_url).where(
                    BusinessContact.business_id == business.id, BusinessContact.type == ContactType.EMAIL
                )
            )
        ).all()
        attach_known_emails(merged, [(e, u or "") for e, u in emails], business.normalized_domain)
        top = merged[0]
        await self._person_profiles(business, top)
        if not top.has_direct_contact:
            await self._paid_contact(business, top)
        for dm in merged:
            await self._save_person(business, dm, sets)
        self._people_found += 1
        if top.has_direct_contact:
            self._direct_found += 1
        return True

    async def _linkedin_people(self, business: Business, roles: tuple[str, ...]) -> list[DecisionMaker]:
        if self._people_search_blocked:
            return []
        key = await self._search_key()
        limit = get_settings().person_search_daily_limit
        if not key or not await take_quota(self.campaign.workspace_id, "people_search", limit):
            return []
        try:
            people = await search_linkedin(
                business.name, key, transport=self.search_transport, roles=roles, place=self._place
            )
            self._record_usage("brave", "people_search", get_settings().cost_brave_per_request)
            return people
        except SearchBlocked as exc:
            self._people_search_blocked = True
            log.info("people search stopped", extra={"error": str(exc)[:200]})
        except httpx.HTTPError as exc:
            log.info("people search failed", extra={"error": str(exc)[:200]})
        return []

    async def _person_profiles(self, business: Business, dm: DecisionMaker) -> None:
        """The decision maker's own LinkedIn/Instagram/X/Facebook accounts, searched by name + business."""
        s = get_settings()
        if self._person_search_blocked:
            return
        platforms = [
            p.strip() for p in s.person_search_platforms.split(",") if p.strip() and p.strip() not in dm.profiles
        ]
        key = await self._search_key() if platforms else None
        if not key:
            return
        if not await take_quota(self.campaign.workspace_id, "person_search", s.person_search_daily_limit):
            self._person_search_blocked = True
            return
        handles = [
            v.rstrip("/").rsplit("/", 1)[-1].lstrip("@")
            for v in await self.db.scalars(
                select(BusinessContact.value).where(
                    BusinessContact.business_id == business.id, BusinessContact.type == ContactType.SOCIAL
                )
            )
        ]
        try:
            calls = await search_person_profiles(
                dm,
                business.name,
                platforms,
                key,
                country=business.country,
                domain=business.normalized_domain,
                handles=handles,
                transport=self.search_transport,
                place=self._place,
            )
            if calls:
                self._record_usage("brave", "person_search", s.cost_brave_per_request, units=calls)
        except SearchBlocked as exc:
            self._person_search_blocked = True
            log.info("person search stopped", extra={"error": str(exc)[:200]})
        except httpx.HTTPError as exc:
            log.info("person search failed", extra={"error": str(exc)[:200]})

    async def _people_finders(self) -> list[tuple[str, Any]]:
        """Connected paid people finders in the configured order, each with its provider context."""
        if self._finders is None:
            self._finders = []
            for key in people_finders.finder_order():
                state = await provider_svc.provider_state(self.db, self.campaign.workspace_id, key)
                if state.status == ProviderStatus.CONNECTED:
                    ctx = await provider_svc.build_context(self.db, self.campaign.workspace_id, key, self.campaign.id)
                    self._finders.append((key, ctx))
        return [(k, c) for k, c in self._finders if k not in self._finder_off]

    async def _paid_contact(self, business: Business, dm: DecisionMaker) -> None:
        for key, ctx in await self._people_finders():
            if key == "hunter" and not business.normalized_domain:
                continue
            try:
                if await people_finders.find_contact(
                    key,
                    ctx,
                    dm,
                    domain=business.normalized_domain,
                    company=business.name,
                    country=business.country,
                    transport=self.finder_transport,
                ):
                    return
            except RateLimited:
                self._finder_off.add(key)
                await provider_svc.mark_rate_limited(self.campaign.workspace_id, key, 60)
                await self._finder_event(key, "people_finder_rate_limited", f"{key} rate limited; skipped for this run")
            except ProviderError as exc:
                if exc.status_code in (401, 402, 403):
                    self._finder_off.add(key)  # account problem: no point asking again this run
                    await self._finder_event(key, "people_finder_error", f"{key}: {exc}")
                log.info("people finder failed", extra={"provider": key, "error": str(exc)[:200]})
            except httpx.HTTPError as exc:
                log.info("people finder failed", extra={"provider": key, "error": str(exc)[:200]})

    async def _apollo_people(self, business: Business, roles: tuple[str, ...]) -> list[DecisionMaker]:
        finders = dict(await self._people_finders())
        if "apollo" not in finders:
            return []
        titles = [r for r in roles if r.isascii()]
        try:
            return await people_finders.apollo_name_people(
                finders["apollo"], business.normalized_domain, titles, business.country, self.finder_transport
            )
        except (ProviderError, httpx.HTTPError) as exc:
            if isinstance(exc, ProviderError) and exc.status_code in (401, 402, 403, 429):
                self._finder_off.add("apollo")
            log.info("apollo people search failed", extra={"error": str(exc)[:200]})
            return []

    async def _finder_event(self, key: str, event_type: str, message: str) -> None:
        if f"noted:{key}" in self._finder_off:
            return
        self._finder_off.add(f"noted:{key}")
        await self.event(
            Stage.CONTACT_ENRICHMENT,
            event_type,
            message,
            level="warning",
            provider_key=key,
            t=event_type,
            p={"provider": key},
        )

    async def _save_person(self, business: Business, dm: DecisionMaker, sets: dict[str, set[str]]) -> None:
        """One PERSON row per decision maker plus one row per direct channel, each tagged with their name."""
        sources = "+".join(dm.sources) if dm.sources else dm.source
        await self._upsert_contact(
            business,
            ContactFinding(
                ContactType.PERSON,
                dm.email or dm.linkedin_url or dm.name,
                f"person:{dm.key}",
                dm.source_url,
                subtype=PERSON_CHANNEL,
                confidence=dm.confidence,
                verification_status=VerificationStatus.DISCOVERED,
                usage_restrictions=PERSON_NOTE,
                person_name=dm.name,
                person_role=dm.role,
                source_provider=sources[:40],
            ),
            sets,
        )
        channels = [
            (ContactType.EMAIL, "email", dm.email),
            (ContactType.PHONE, "phone", dm.phone),
            (ContactType.WHATSAPP, "whatsapp", dm.whatsapp),
        ]
        for ctype, kind, value in channels:
            if not value:
                continue
            provider = dm.channel_sources.get(kind) or dm.source
            await self._upsert_person_channel(
                business,
                ContactFinding(
                    ctype,
                    value,
                    value.lower(),
                    dm.channel_urls.get(kind) or dm.source_url,
                    subtype=PERSON_CHANNEL,
                    confidence=min(dm.confidence, 0.85),
                    usage_restrictions=PERSON_NOTE,
                    person_name=dm.name,
                    person_role=dm.role,
                    source_provider=provider[:40],
                ),
                sets,
            )
        for platform, url in dm.profiles.items():
            await self._upsert_person_channel(
                business,
                ContactFinding(
                    ContactType.SOCIAL,
                    url,
                    url.lower(),
                    url,
                    subtype=PERSON_CHANNEL,
                    confidence=min(dm.confidence, 0.7),
                    usage_restrictions=PERSON_NOTE,
                    person_name=dm.name,
                    person_role=f"{dm.role} · {platform}"[:200],
                    source_provider=dm.channel_sources.get(f"profile:{platform}", dm.source)[:40],
                ),
                sets,
            )

    async def _upsert_person_channel(self, business: Business, f: ContactFinding, sets: dict[str, set[str]]) -> None:
        """Like _upsert_contact, but an existing row with the same value (e.g. found on the site as a plain
        business email) is re-labelled as this person's, since the person was named next to it."""
        existing = await self.db.scalar(
            select(BusinessContact).where(
                BusinessContact.business_id == business.id,
                BusinessContact.type == f.type,
                BusinessContact.normalized_value == f.normalized_value,
            )
        )
        if existing is not None and not existing.person_name:
            existing.person_name = f.person_name
            existing.person_role = f.person_role
            existing.subtype = PERSON_CHANNEL
            existing.usage_restrictions = existing.usage_restrictions or f.usage_restrictions
        await self._upsert_contact(business, f, sets)

    async def _search_key(self) -> str | None:
        if self._brave_key is False:
            state = await provider_svc.provider_state(self.db, self.campaign.workspace_id, "brave")
            creds = (
                (await provider_svc.credentials_for(self.db, self.campaign.workspace_id, "brave"))[0]
                if state.status == ProviderStatus.CONNECTED
                else {}
            )
            self._brave_key = creds.get("api_key") or None
        return self._brave_key or None

    async def _social_search(self, business: Business, sets: dict[str, set[str]]) -> None:
        """Look up the business's own profiles by name on platforms it did not link to (see social_search)."""
        s = get_settings()
        if self.campaign.is_demo or not s.social_search_enabled or self._search_blocked:
            return
        wanted = [p.strip() for p in s.social_search_platforms.split(",") if p.strip() in SEARCH_PLATFORMS]
        have = set(
            await self.db.scalars(
                select(BusinessContact.subtype).where(
                    BusinessContact.business_id == business.id, BusinessContact.type == ContactType.SOCIAL
                )
            )
        )
        missing = [p for p in wanted if p not in have]
        if not missing:
            return
        phones = list(
            await self.db.scalars(
                select(BusinessContact.normalized_value).where(
                    BusinessContact.business_id == business.id,
                    BusinessContact.type.in_([ContactType.PHONE, ContactType.WHATSAPP]),
                )
            )
        )
        key = await self._search_key()
        if not key:
            self._search_blocked = True  # checked once per run
            await self.event(
                Stage.CONTACT_ENRICHMENT,
                "social_search_needs_key",
                "Search by name is on but needs a connected Brave Search key; skipped.",
                t="social_search_needs_key",
            )
            return
        for platform in missing:
            if not await take_quota(self.campaign.workspace_id, "social_search", s.social_search_daily_limit):
                self._search_blocked = True
                await self.event(
                    Stage.CONTACT_ENRICHMENT,
                    "social_search_quota",
                    f"Daily social search limit ({s.social_search_daily_limit}) reached; search by name stopped.",
                    level="warning",
                    t="social_search_quota",
                    p={"limit": s.social_search_daily_limit},
                )
                return
            try:
                hits = await web_search(
                    build_query(business.name, business.city, platform),
                    brave_key=key,
                    transport=self.search_transport,
                    place=self._place,
                )
            except SearchBlocked as exc:
                self._search_blocked = True
                await self.event(
                    Stage.CONTACT_ENRICHMENT,
                    "social_search_blocked",
                    f"Social search by name stopped: {exc}",
                    level="warning",
                    t="social_search_blocked",
                    p={"error": str(exc)},
                )
                return
            except httpx.HTTPError as exc:
                log.info("social search failed", extra={"business": business.name, "error": str(exc)[:200]})
                continue
            match = best_match(hits, platform, business.name, domain=business.normalized_domain, phones=phones)
            if match:
                self._search_found += 1
                await self._upsert_contact(
                    business,
                    ContactFinding(
                        ContactType.SOCIAL,
                        match.url,
                        match.url.lower(),
                        match.source_url,
                        subtype=platform,
                        confidence=match.confidence,
                        usage_restrictions=None if match.strong else NAME_ONLY_NOTE,
                        source_provider="social_search",
                    ),
                    sets,
                )

    async def _social_enrich(self, business: Business, source: PageSource, sets: dict[str, set[str]]) -> None:
        """Read the public pages of social profiles this business published. Idempotent per profile URL."""
        rows = await self.db.scalars(
            select(BusinessContact).where(
                BusinessContact.business_id == business.id, BusinessContact.type == ContactType.SOCIAL
            )
        )
        done = set(
            await self.db.scalars(
                select(BusinessEvidence.url).where(
                    BusinessEvidence.business_id == business.id, BusinessEvidence.kind == "social_profile"
                )
            )
        )
        todo = [c for c in rows if c.value not in done and c.subtype in SOCIAL_PLATFORMS]
        for contact in todo[: get_settings().social_profiles_per_business]:
            platform = platform_of(contact.value)
            try:
                profile = await fetch_profile(source, contact.value, logged_in=await self._use_session(platform))
            except SessionExpired as exc:
                self._sessions.pop(exc.platform, None)
                await mark_expired(self.db, self.campaign.workspace_id, exc.platform)
                await self.event(
                    Stage.CONTACT_ENRICHMENT,
                    "session_expired",
                    str(exc),
                    level="warning",
                    t="session_expired",
                    p={"platform": exc.platform},
                )
                continue
            except ScrapeBlocked as exc:
                self._social_blocked = True
                self.partial_reasons.append("Social profile pages blocked automated access")
                await self.event(
                    Stage.CONTACT_ENRICHMENT,
                    "provider_blocked",
                    f"Social enrichment stopped: {exc}",
                    level="warning",
                    t="social_blocked",
                    p={"error": str(exc)},
                )
                return
            except BrowserUnavailable as exc:
                self._social_blocked = True
                await self.event(
                    Stage.CONTACT_ENRICHMENT,
                    "provider_unavailable",
                    f"Social enrichment off: {exc}",
                    level="warning",
                    t="social_off",
                    p={"error": str(exc)},
                )
                return
            except Exception as exc:  # noqa: BLE001 - one bad page must not stop the lead
                log.info("social profile skipped", extra={"url": contact.value, "error": str(exc)[:200]})
                continue
            if profile is None:
                continue
            try:
                excerpt = profile.summary()[:2000]
            except Exception as exc:  # noqa: BLE001 - an odd profile page must not stop the whole run
                log.info("social profile summary failed", extra={"url": contact.value, "error": str(exc)[:200]})
                continue
            self.db.add(
                BusinessEvidence(
                    business_id=business.id,
                    kind="social_profile",
                    signal_key=f"social:{profile.platform}",
                    url=contact.value,
                    title=f"{profile.platform.title()} profile" + (f": {profile.name}" if profile.name else ""),
                    excerpt=excerpt,
                    observed=profile.accessible,
                    captured_at=datetime.now(UTC),
                )
            )
            if not profile.accessible:
                continue
            emails, phones = contacts_in_bio(profile)
            for raw in emails:
                email = normalize_email(raw)
                if email:
                    subtype, conf, restriction = classify_email(email, business.normalized_domain)
                    await self._upsert_contact(
                        business,
                        ContactFinding(
                            ContactType.EMAIL,
                            email,
                            email,
                            profile.url,
                            subtype=subtype,
                            confidence=min(conf, 0.6),
                            usage_restrictions=restriction,
                            source_provider=profile.platform,
                        ),
                        sets,
                    )
            for raw in phones:
                phone = normalize_phone(raw, business.country)
                if phone:
                    await self._upsert_contact(
                        business,
                        ContactFinding(
                            ContactType.PHONE,
                            raw.strip(),
                            phone,
                            profile.url,
                            subtype="social_bio",
                            confidence=0.6,
                            source_provider=profile.platform,
                        ),
                        sets,
                    )
            if profile.website and not business.website_url:
                await self._adopt_website(business, profile.website)

    async def _adopt_website(self, business: Business, url: str) -> None:
        """Use a website a business links from its own profile, unless another record already owns it."""
        domain = business_domain(url)
        if not domain:
            return
        taken = await self.db.scalar(
            select(Business.id).where(
                Business.workspace_id == business.workspace_id,
                Business.normalized_domain == domain,
                Business.deleted_at.is_(None),
            )
        )
        if taken is None:
            business.website_url = homepage_url(url)
            business.normalized_domain = domain

    async def _research(self, business: Business, transport: httpx.AsyncBaseTransport | None) -> WebsiteResearch:
        if not business.website_url:
            return WebsiteResearch(url="", reachable=False, error="No website known")
        return await research_website(
            business.website_url,
            country=business.country,
            max_pages=int(self.settings["max_pages_per_site"]),
            transport=transport,
            skip_dns_check=transport is not None and self.campaign.is_demo,
            roles=self._roles or (),  # resolved once in stage_enrichment (no DB calls inside gather)
        )

    async def _save_research(self, business: Business, res: WebsiteResearch, sets: dict[str, set[str]]) -> None:
        now = datetime.now(UTC)
        await self.db.execute(
            delete(BusinessEvidence).where(
                BusinessEvidence.business_id == business.id, BusinessEvidence.kind.not_in(EXTERNAL_EVIDENCE_KINDS)
            )
        )
        for page in res.pages:
            self.db.add(
                BusinessEvidence(
                    business_id=business.id,
                    kind="page",
                    url=page.url,
                    title=page.title,
                    excerpt=page.excerpt[:2000],
                    signal_key=f"page:{page.kind}",
                    captured_at=now,
                )
            )
        for s in res.signals:
            self.db.add(
                BusinessEvidence(
                    business_id=business.id,
                    kind="signal",
                    signal_key=s.key,
                    url=s.url,
                    title=s.label,
                    excerpt=s.excerpt,
                    observed=s.observed,
                    captured_at=now,
                )
            )
        if not res.reachable:
            self.db.add(
                BusinessEvidence(
                    business_id=business.id,
                    kind="error",
                    signal_key="unreachable",
                    url=res.url or None,
                    title="Website not inspected",
                    excerpt=res.error,
                    observed=False,
                    captured_at=now,
                )
            )
        if res.description and not business.description:
            business.description = res.description[:2000]
        if business.name == business.normalized_domain:
            if res.structured_name:
                business.name = res.structured_name
            elif res.title:
                business.name = res.title.split("|")[0].strip()[:300] or business.name
        if res.address and not business.address:
            business.address = res.address
        if res.opening_hours:
            self.db.add(
                BusinessEvidence(
                    business_id=business.id,
                    kind="structured",
                    signal_key="opening_hours",
                    url=res.url,
                    title="Opening hours (schema.org data on the website)",
                    excerpt=res.opening_hours,
                    captured_at=now,
                )
            )
        for finding in res.contacts.contacts:
            await self._upsert_contact(business, finding, sets)
        business.last_enriched_at = now

    async def _upsert_contact(self, business: Business, f: ContactFinding, sets: dict[str, set[str]]) -> None:
        existing = await self.db.scalar(
            select(BusinessContact).where(
                BusinessContact.business_id == business.id,
                BusinessContact.type == f.type,
                BusinessContact.normalized_value == f.normalized_value,
            )
        )
        restriction = f.usage_restrictions
        if business.is_demo:
            restriction = "DEMO: fictional contact value. Not a real business."
        if existing:
            existing.confidence = max(existing.confidence, f.confidence)
            existing.retrieved_at = datetime.now(UTC)
            existing.source_url = existing.source_url or f.source_url
            return
        self.db.add(
            BusinessContact(
                business_id=business.id,
                type=f.type,
                subtype=f.subtype,
                value=f.value[:500],
                normalized_value=f.normalized_value[:500],
                source_url=f.source_url,
                source_provider=f.source_provider,
                verification_status=f.verification_status,
                confidence=f.confidence,
                usage_restrictions=restriction,
                person_name=f.person_name,
                person_role=f.person_role,
                is_suppressed=contact_is_suppressed(f.type, f.normalized_value, sets),
            )
        )
        await self.db.flush()

    async def _hunter_enrich(
        self, business: Business, ctx: Any, sets: dict[str, set[str]], *, search: bool = True
    ) -> None:
        allow_named = True  # decision makers are always delivered (see _decision_makers)
        try:
            async with HunterClient(ctx) as hunter:
                data = (
                    await hunter.domain_search(business.normalized_domain, include_personal=allow_named)
                    if search
                    else {}
                )
                for e in data.get("emails", []):
                    value = (e.get("value") or "").lower()
                    if not value:
                        continue
                    subtype, conf, restriction = classify_email(value, business.normalized_domain)
                    sources = e.get("sources") or []
                    is_person = e.get("type") == "personal"
                    if is_person and not allow_named:
                        continue
                    await self._upsert_contact(
                        business,
                        ContactFinding(
                            type=ContactType.PERSON if is_person else ContactType.EMAIL,
                            value=value,
                            normalized_value=value,
                            source_url=(sources[0].get("uri") if sources else None) or "https://hunter.io",
                            subtype=subtype,
                            confidence=min((e.get("confidence") or 50) / 100, 0.95),
                            usage_restrictions=restriction or "Licensed via Hunter.io; respect Hunter terms of use.",
                            person_name=" ".join(filter(None, [e.get("first_name"), e.get("last_name")])) or None,
                            person_role=e.get("position"),
                            source_provider="hunter",
                        ),
                        sets,
                    )
                if not business.description and data.get("description"):
                    business.description = data["description"][:2000]
                if self.settings["email_verification"]:
                    emails = await self.db.scalars(
                        select(BusinessContact).where(
                            BusinessContact.business_id == business.id,
                            BusinessContact.type == ContactType.EMAIL,
                            BusinessContact.verification_status.in_(
                                [VerificationStatus.DISCOVERED, VerificationStatus.UNVERIFIED]
                            ),
                        )
                    )
                    for contact in list(emails)[:3]:
                        v = await hunter.verify(contact.normalized_value)
                        status = v.get("status")
                        contact.verification_status = {
                            "valid": VerificationStatus.VERIFIED,
                            "invalid": VerificationStatus.INVALID,
                        }.get(status, VerificationStatus.UNVERIFIED)
                        contact.verified_at = datetime.now(UTC)
        except RateLimited:
            self._set_checkpoint(rate_limit_warnings=int(self.checkpoint.get("rate_limit_warnings", 0)) + 1)
            await provider_svc.mark_rate_limited(self.campaign.workspace_id, "hunter", 60)
            await self.event(
                Stage.CONTACT_ENRICHMENT,
                "rate_limited",
                "Hunter rate limited; skipping for this lead",
                level="warning",
                provider_key="hunter",
                t="hunter_rate_limited",
            )
        except (ProviderError, httpx.HTTPError) as exc:
            await self.event(
                Stage.CONTACT_ENRICHMENT,
                "provider_error",
                f"Hunter: {exc}",
                level="warning",
                provider_key="hunter",
                t="hunter_error",
                p={"error": str(exc)},
            )

    async def _mx_check(self, business: Business) -> None:
        """Mark emails whose domain cannot receive mail as invalid. Never upgrades anything to 'verified'."""
        await self.db.flush()
        emails = await self.db.scalars(
            select(BusinessContact).where(
                BusinessContact.business_id == business.id,
                BusinessContact.type.in_([ContactType.EMAIL, ContactType.PERSON]),
                BusinessContact.verification_status.in_([VerificationStatus.DISCOVERED, VerificationStatus.UNKNOWN]),
            )
        )
        cache = self.__dict__.setdefault("_mx_cache", {})
        for contact in emails:
            domain = contact.normalized_value.rpartition("@")[2]
            if not domain:
                continue
            accepts = await domain_accepts_mail(domain, cache)
            if accepts is False:
                contact.verification_status = VerificationStatus.INVALID
                contact.verified_at = datetime.now(UTC)
                contact.usage_restrictions = f"Domain {domain} has no mail server (DNS MX/A check)."
            elif accepts:
                contact.confidence = min(contact.confidence + 0.05, 0.95)

    async def _demo_verify(self, business: Business) -> None:
        """DEMO MODE only: fictional verification so the workflow can be demonstrated end to end."""
        emails = await self.db.scalars(
            select(BusinessContact).where(
                BusinessContact.business_id == business.id, BusinessContact.type == ContactType.EMAIL
            )
        )
        for c in emails:
            c.verification_status = (
                VerificationStatus.VERIFIED if c.subtype == "general" else VerificationStatus.UNVERIFIED
            )
            c.verified_at = datetime.now(UTC)
            c.usage_restrictions = "DEMO: fictional verification result."

    async def _refresh_contact_flags(self, business: Business) -> None:
        await self.db.flush()
        rows = (
            await self.db.execute(
                select(BusinessContact.type, BusinessContact.verification_status).where(
                    BusinessContact.business_id == business.id
                )
            )
        ).all()
        business.contact_count = len(rows)
        business.has_verified_contact = any(
            v == VerificationStatus.VERIFIED and t in (ContactType.EMAIL, ContactType.PHONE) for t, v in rows
        )

    async def _evidence_for(self, business: Business) -> list[dict]:
        rows = await self.db.scalars(
            select(BusinessEvidence)
            .where(BusinessEvidence.business_id == business.id)
            .order_by(BusinessEvidence.kind, BusinessEvidence.signal_key)
        )
        evidence = []
        for i, e in enumerate(rows, start=1):
            item = {
                "id": f"E{i}",
                "kind": e.kind,
                "url": e.url,
                "title": e.title,
                "excerpt": (e.excerpt or "")[:1200],
                "observed": e.observed,
            }
            if e.kind == "signal":
                item["signal"] = e.signal_key
                item["label"] = e.title
                item["observed_note"] = "observed" if e.observed else "not observed on inspected pages"
            evidence.append(item)
        return evidence

    async def stage_analysis(self) -> None:
        leads = await self._pending_leads("analyzed")
        creds = {}
        for key in AI_PROVIDERS:
            c, _ = await provider_svc.credentials_for(self.db, self.campaign.workspace_id, key)
            state = await provider_svc.provider_state(self.db, self.campaign.workspace_id, key)
            if state.status.value == "connected":
                creds[key] = c
        ai = AIService(creds)
        mode = "demo" if self.campaign.is_demo else (ai.provider or "heuristic")
        self._set_checkpoint(ai_provider=mode)
        if mode == "heuristic":
            self.partial_reasons.append("AI provider not configured; rule-based analysis used")
            await self.event(
                Stage.AI_ANALYSIS,
                "provider_unavailable",
                "No AI provider configured: using the rule-based analyzer (labelled 'heuristic').",
                level="warning",
                provider_key="anthropic",
                t="no_ai",
            )
        target = {
            "industry": self.campaign.industry,
            "country": self.campaign.country,
            "city": self.campaign.city,
            "keywords": self.campaign.keywords,
            "characteristics": self.campaign.characteristics,
            "services": self.campaign.services,
        }
        profile = await self.db.scalar(
            select(WorkspaceProfile).where(WorkspaceProfile.workspace_id == self.campaign.workspace_id)
        )
        seller = seller_context(profile, list(self.campaign.services or [])) if profile else {}
        for lead, business in leads:
            await self.check_control()
            evidence = await self._evidence_for(business)
            biz = {
                "name": business.name,
                "website": business.website_url,
                "industry": business.industry,
                "city": business.city,
                "country": business.country,
                "description": business.description,
            }
            await self.push_progress(
                activity=f"Analyzing {business.name}", provider=mode, activity_t=("analyzing", {"name": business.name})
            )
            usage = {"provider": mode, "model": None, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
            analysis: BusinessAnalysis
            try:
                if mode in AI_PROVIDERS:
                    result = await ai.analyze_business(business=biz, evidence=evidence, target=target, seller=seller)
                    analysis = result.output
                    usage = {
                        "provider": result.provider,
                        "model": result.model,
                        "input_tokens": result.input_tokens,
                        "output_tokens": result.output_tokens,
                        "cost_usd": result.cost_usd,
                    }
                else:
                    analysis = heuristic_analysis(business=biz, evidence=evidence, target=target, seller=seller)
            except (AIUnavailable, AIRefused) as exc:
                lead.processing_error = f"analysis: {exc}"[:500]
                analysis = heuristic_analysis(business=biz, evidence=evidence, target=target, seller=seller)
                usage["provider"] = "heuristic"
                await self.event(
                    Stage.AI_ANALYSIS,
                    "analysis_fallback",
                    f"AI analysis unavailable for {business.name}: {exc}. Rule-based result stored.",
                    level="warning",
                    t="analysis_fallback",
                    p={"name": business.name, "error": str(exc)},
                )
            except Exception as exc:  # provider/network errors: isolate per lead
                lead.processing_error = f"analysis: {type(exc).__name__}: {exc}"[:500]
                lead.analyzed = True
                await self.event(
                    Stage.AI_ANALYSIS,
                    "lead_failed",
                    f"Analysis failed for {business.name}: {exc}",
                    level="error",
                    t="analysis_failed",
                    p={"name": business.name, "error": str(exc)},
                )
                await self.db.commit()
                continue
            ev_by_id = {e["id"]: e for e in evidence}
            self.db.add(
                LeadAssessment(
                    business_id=business.id,
                    campaign_id=self.campaign.id,
                    summary=analysis.business_summary,
                    observed_signals=[s.model_dump() for s in analysis.observed_signals],
                    hypotheses=[h.model_dump() for h in analysis.hypotheses],
                    potential_problems=analysis.potential_problems,
                    evidence_links=[
                        {"id": i, "url": ev_by_id[i].get("url"), "title": ev_by_id[i].get("title")}
                        for i in sorted({i for s in analysis.observed_signals for i in s.evidence_ids})
                        if i in ev_by_id
                    ],
                    recommended_services=[r.model_dump() for r in analysis.recommended_services],
                    opportunity=analysis.opportunity,
                    suggested_pitch=analysis.suggested_pitch,
                    unknowns=analysis.unknowns,
                    confidence=analysis.confidence,
                    industry_fit=analysis.industry_fit,
                    characteristics_fit=analysis.characteristics_fit,
                    **usage,
                )
            )
            business.recommended_service = (
                analysis.recommended_services[0].service if analysis.recommended_services else None
            )
            business.last_analyzed_at = datetime.now(UTC)
            lead.analyzed = True
            await self.db.commit()
        if self.only_business is not None:  # one lead: the campaign's own stage state is untouched
            return
        await self._complete_stage(Stage.AI_ANALYSIS)
        await self.event(
            Stage.AI_ANALYSIS, "stage_done", f"Analysis completed ({mode})", t="analysis_done", p={"mode": mode}
        )
        await self.push_progress(force=True)

    async def stage_scoring(self) -> None:
        leads = await self._pending_leads("scored")
        ws_settings = (self.workspace.settings if self.workspace else {}) or {}
        weights = ws_settings.get("scoring_weights")
        thresholds = ws_settings.get("scoring_thresholds")
        min_score = float(self.settings["min_score"])
        for lead, business in leads:
            await self.check_control()
            # Leads that skipped enrichment (enrichment off) still deliver their listing contacts.
            await self._charge_lead(lead, business)
            assessment = await self.db.scalar(
                select(LeadAssessment)
                .where(LeadAssessment.business_id == business.id)
                .order_by(LeadAssessment.created_at.desc())
                .limit(1)
            )
            contacts = (
                await self.db.scalars(
                    select(BusinessContact).where(
                        BusinessContact.business_id == business.id, BusinessContact.is_suppressed.is_(False)
                    )
                )
            ).all()
            summary = ContactSummary()
            for c in contacts:
                if c.verification_status == VerificationStatus.INVALID:
                    continue
                if (
                    c.type in (ContactType.EMAIL, ContactType.PHONE)
                    and c.verification_status == VerificationStatus.VERIFIED
                ):
                    summary.verified_direct += 1
                elif c.type == ContactType.EMAIL and c.subtype not in ("individual",):
                    summary.discovered_role_email += 1
                elif c.type in (ContactType.PHONE, ContactType.WHATSAPP):
                    summary.discovered_phone_or_whatsapp += 1
                elif c.type in (ContactType.CONTACT_PAGE, ContactType.SOCIAL):
                    summary.indirect_only += 1
            ev = (
                await self.db.execute(
                    select(BusinessEvidence.kind, BusinessEvidence.signal_key, BusinessEvidence.observed).where(
                        BusinessEvidence.business_id == business.id
                    )
                )
            ).all()
            pages = sum(1 for k, _, _ in ev if k == "page")
            signals = sum(1 for k, key, o in ev if k == "signal" and o and key not in BASELINE_SIGNALS)
            external = sum(1 for k, _, o in ev if k in EXTERNAL_EVIDENCE_KINDS and o)
            recommended = [r["service"] for r in (assessment.recommended_services if assessment else [])]
            result = score_lead(
                ScoringInput(
                    industry_matches_target=(business.industry == self.campaign.industry),
                    ai_industry_fit=assessment.industry_fit if assessment else None,
                    recommended_services=recommended,
                    wanted_services=list(self.campaign.services or []),
                    contacts=summary,
                    observed_signal_count=signals,
                    pages_inspected=pages,
                    assessment_confidence=assessment.confidence if assessment else None,
                    characteristics_fit=assessment.characteristics_fit if assessment else None,
                    has_target_characteristics=bool(self.campaign.characteristics),
                    last_enriched_at=business.last_enriched_at,
                    website_reachable=pages > 0,
                    external_observations=external,
                ),
                weights,
                thresholds,
            )
            self.db.add(
                LeadScore(
                    business_id=business.id,
                    campaign_id=self.campaign.id,
                    assessment_id=assessment.id if assessment else None,
                    total=result.total,
                    priority=result.priority,
                    factors=result.factors,
                    weights=result.weights,
                    explanation=result.explanation,
                    scoring_version=result.version,
                )
            )
            lead.score = result.total
            lead.priority = result.priority
            lead.qualified = result.total >= min_score and result.priority != Priority.NEEDS_REVIEW
            lead.scored = True
            business.latest_score = result.total
            business.latest_priority = result.priority
            await self.db.commit()
            await self.push_progress(
                activity=f"Scored {business.name}: {result.total}",
                activity_t=("scored", {"name": business.name, "score": result.total}),
            )
        if self.only_business is not None:
            return
        await self._complete_stage(Stage.LEAD_SCORING)
        stats = await self.compute_stats()
        await self.event(
            Stage.LEAD_SCORING,
            "stage_done",
            f"Scoring completed: {stats['qualified']} qualified of {stats['unique_leads']} (target {stats['target']})",
            t="scoring_done",
            p={"qualified": stats["qualified"], "total": stats["unique_leads"], "target": stats["target"]},
        )


async def start_new_run(db: AsyncSession, campaign: Campaign, celery_task_id: str | None = None) -> CampaignRun:
    last = await db.scalar(select(func.max(CampaignRun.run_number)).where(CampaignRun.campaign_id == campaign.id))
    run = CampaignRun(
        campaign_id=campaign.id,
        run_number=(last or 0) + 1,
        status=CampaignStatus.QUEUED,
        checkpoint={},
        counters={},
        celery_task_id=celery_task_id,
    )
    db.add(run)
    await db.flush()
    return run


async def execute_campaign(
    db: AsyncSession,
    campaign_id: uuid.UUID,
    run_id: uuid.UUID,
    site_transport: httpx.AsyncBaseTransport | None = None,
    page_source: PageSource | None = None,
    search_transport: httpx.AsyncBaseTransport | None = None,
    finder_transport: httpx.AsyncBaseTransport | None = None,
) -> CampaignStatus | None:
    """Entry point used by the Celery worker (and tests). Idempotent: finished runs are not re-executed."""
    campaign = await db.get(Campaign, campaign_id)
    run = await db.get(CampaignRun, run_id)
    if campaign is None or run is None or campaign.deleted_at is not None:
        return None
    if run.finished_at is not None:
        return CampaignStatus(run.status)
    if campaign.status in (CampaignStatus.PAUSED, CampaignStatus.CANCELLED):
        return CampaignStatus(campaign.status)
    await db.refresh(campaign, attribute_names=["sources"])
    pipeline = CampaignPipeline(
        db,
        campaign,
        run,
        site_transport=site_transport,
        page_source=page_source,
        search_transport=search_transport,
        finder_transport=finder_transport,
    )
    status = await pipeline.execute()
    if status in (CampaignStatus.COMPLETED, CampaignStatus.PARTIALLY_COMPLETED, CampaignStatus.FAILED):
        from app.services.notifications import notify_campaign_finished

        try:
            await notify_campaign_finished(db, campaign)
        except Exception:  # noqa: BLE001 - notification failure must not change campaign outcome
            log.exception("completion notification failed")
    return status
