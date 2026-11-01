"""Credits: what is charged, stopping at zero, concurrency, and the start/estimate gates.

Campaigns use the import provider with phone numbers only (no websites), so nothing touches the network.
"""

import asyncio
import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.models import CampaignLead, CampaignRun, CreditTransaction, Workspace
from app.models.enums import CreditKind
from app.research.pipeline import execute_campaign
from app.services import credits as credit_svc
from tests.conftest import login, make_user, run_latest


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "scraping_enabled", False)
    monkeypatch.setattr(s, "email_mx_check", False)


@pytest.fixture
async def metered(app, db):
    """A metered (non-exempt) workspace and a logged-in owner client; fund it with `credit_svc.grant`."""
    user, ws = await make_user(db, billing_exempt=False)
    client = await login(app, user.email)
    yield client, ws
    await client.aclose()


async def fund(db, ws: Workspace, amount: int, kind: CreditKind = CreditKind.PURCHASE) -> None:
    await credit_svc.grant(db, ws.id, amount, kind)
    await db.commit()


async def balance(db, ws: Workspace | uuid.UUID) -> int:
    ws_id = ws if isinstance(ws, uuid.UUID) else ws.id
    return await db.scalar(
        select(Workspace.credit_balance).where(Workspace.id == ws_id).execution_options(populate_existing=True)
    )


def rows(tag: str, with_phone: int, without: int = 0) -> list[str]:
    out = [
        {"name": f"{tag} Clinic {i}", "phone": f"+9661123{abs(hash(tag)) % 1000:03d}{i:02d}", "line": i + 2}
        for i in range(with_phone)
    ]
    out += [{"name": f"{tag} Shop {i}", "line": 100 + i} for i in range(without)]
    return [json.dumps(r) for r in out]


def campaign_body(name: str, entries: list[str], **settings) -> dict:
    return {
        "name": name,
        "country": "SA",
        "city": "Riyadh",
        "industry": "dental_clinics",
        "sources": [{"provider_key": "import", "manual_urls": entries}],
        "settings": {"target_count": 20, "max_companies": 20, "min_score": 0, "ai_analysis": False, **settings},
        "start": True,
    }


async def start(client, body: dict) -> dict:
    r = await client.post("/api/v1/campaigns", json=body)
    assert r.status_code == 201, r.text
    return r.json()


async def charges(db, campaign_id: str) -> list[CreditTransaction]:
    q = select(CreditTransaction).where(
        CreditTransaction.campaign_id == uuid.UUID(campaign_id), CreditTransaction.kind == CreditKind.CAMPAIGN_CHARGE
    )
    return list((await db.scalars(q)).all())


async def test_only_new_businesses_with_a_usable_contact_are_charged(metered, db, dispatched):
    client, ws = metered
    await fund(db, ws, 10)
    entries = rows("alpha", with_phone=3, without=2)
    camp = await start(client, campaign_body("A", entries))
    assert await run_latest(camp["id"]) == "completed"
    assert await balance(db, ws) == 7  # 3 with a phone; the 2 without any contact are free
    txs = await charges(db, camp["id"])
    assert len(txs) == 3 and all(t.delta == -1 and t.business_id for t in txs)
    assert sorted(t.balance_after for t in txs) == [7, 8, 9]

    # The same businesses again: already known to the workspace (pre_existing), so not charged twice.
    again = await start(client, campaign_body("A again", entries))
    assert await run_latest(again["id"]) == "completed"
    leads = (await db.scalars(select(CampaignLead).where(CampaignLead.campaign_id == uuid.UUID(again["id"])))).all()
    # Businesses with a phone are recognised; the contact-less ones have no identity to match and come in new.
    assert sum(1 for lead in leads if lead.pre_existing) == 3
    assert await balance(db, ws) == 7 and await charges(db, again["id"]) == []


async def test_suppressed_or_invalid_contacts_are_not_charged(metered, db, dispatched):
    client, ws = metered
    await fund(db, ws, 10)
    entries = rows("beta", with_phone=2)
    blocked = json.loads(entries[0])["phone"]
    r = await client.post("/api/v1/suppression", json={"kind": "phone", "value": blocked})
    assert r.status_code == 201, r.text
    camp = await start(client, campaign_body("B", entries))
    await run_latest(camp["id"])
    assert await balance(db, ws) == 9  # only the business whose phone is not on the do-not-contact list


async def test_enrichment_off_still_charges_delivered_contacts(metered, db, dispatched):
    client, ws = metered
    await fund(db, ws, 10)
    camp = await start(client, campaign_body("C", rows("gamma", with_phone=2), enrichment=False))
    assert await run_latest(camp["id"]) == "completed"
    assert await balance(db, ws) == 8


async def test_demo_campaigns_are_free(metered, db, dispatched):
    client, ws = metered  # no credits at all
    body = {
        "name": "Demo",
        "country": "SA",
        "city": "Riyadh",
        "industry": "dental_clinics",
        "sources": [{"provider_key": "demo"}],
        "settings": {"target_count": 5, "max_companies": 5, "min_score": 0},
        "start": True,
    }
    camp = await start(client, body)
    assert await run_latest(camp["id"]) == "completed"
    assert await balance(db, ws) == 0 and await charges(db, camp["id"]) == []


async def test_run_stops_at_zero_credits_and_resumes_after_top_up(metered, db, dispatched):
    client, ws = metered
    await fund(db, ws, 2)
    camp = await start(client, campaign_body("D", rows("delta", with_phone=5)))
    assert await run_latest(camp["id"]) == "partially_completed"
    assert await balance(db, ws) == 0
    events = (await client.get(f"/api/v1/campaigns/{camp['id']}/events/history")).json()
    stop = [e for e in events if e["event_type"] == "run_stopped"]
    assert stop and stop[-1]["data"]["t"] == "stop_credits_exhausted"
    cid = uuid.UUID(camp["id"])
    leads = (await db.scalars(select(CampaignLead).where(CampaignLead.campaign_id == cid))).all()
    assert sum(1 for x in leads if x.credits_charged) == 2
    assert sum(1 for x in leads if not x.enriched) == 3  # left for a later run, never delivered free

    # Out of credits: retrying is refused until the client tops up; then only the remaining leads are charged.
    r = await client.post(f"/api/v1/campaigns/{camp['id']}/retry")
    assert r.status_code == 402 and r.json()["error"]["code"] == "insufficient_credits"
    await fund(db, ws, 10)
    assert (await client.post(f"/api/v1/campaigns/{camp['id']}/retry")).status_code == 200
    assert await run_latest(camp["id"]) == "completed"
    assert await balance(db, ws) == 7
    assert len(await charges(db, camp["id"])) == 5


async def test_concurrent_charges_never_overdraw(metered, db):
    _, ws = metered
    await fund(db, ws, 5)

    async def one() -> bool:
        async with get_sessionmaker()() as s:
            try:
                await credit_svc.charge(s, ws.id, 1)
                await s.commit()
                return True
            except credit_svc.InsufficientCredits:
                await s.rollback()
                return False

    results = await asyncio.gather(*[one() for _ in range(12)])
    assert sum(results) == 5
    assert await balance(db, ws) == 0
    after = (
        await db.scalars(
            select(CreditTransaction.balance_after).where(
                CreditTransaction.workspace_id == ws.id, CreditTransaction.kind == CreditKind.CAMPAIGN_CHARGE
            )
        )
    ).all()
    assert sorted(after) == [0, 1, 2, 3, 4]


async def test_two_concurrent_campaigns_share_the_balance(metered, db, dispatched):
    client, ws = metered
    await fund(db, ws, 5)
    a = await start(client, campaign_body("E1", rows("eps", with_phone=4), concurrency=1))
    b = await start(client, campaign_body("E2", rows("zeta", with_phone=4), concurrency=1))

    async def run(campaign_id: str) -> str:
        async with get_sessionmaker()() as s:
            run_ = await s.scalar(select(CampaignRun).where(CampaignRun.campaign_id == uuid.UUID(campaign_id)))
            return (await execute_campaign(s, uuid.UUID(campaign_id), run_.id)).value

    statuses = await asyncio.gather(run(a["id"]), run(b["id"]))
    assert "partially_completed" in statuses
    assert await balance(db, ws) == 0
    total = await db.scalar(
        select(func.sum(CreditTransaction.delta)).where(
            CreditTransaction.workspace_id == ws.id, CreditTransaction.kind == CreditKind.CAMPAIGN_CHARGE
        )
    )
    assert total == -5


async def test_start_needs_credits_and_a_live_trial(metered, db, dispatched):
    client, ws = metered
    body = campaign_body("F", rows("eta", with_phone=1))
    r = await client.post("/api/v1/campaigns", json=body)
    assert r.status_code == 402 and r.json()["error"]["code"] == "insufficient_credits"

    # Trial credits after the trial has ended cannot be used.
    await fund(db, ws, 100, CreditKind.TRIAL_GRANT)
    w = await db.get(Workspace, ws.id)
    w.trial_ends_at = datetime.now(UTC) - timedelta(days=1)
    await db.commit()
    r = await client.post("/api/v1/campaigns", json=body)
    assert r.status_code == 402 and r.json()["error"]["code"] == "trial_expired"

    # Within the trial it works; after a purchase the trial end no longer matters.
    w.trial_ends_at = datetime.now(UTC) + timedelta(days=3)
    await db.commit()
    assert (await client.post("/api/v1/campaigns", json=body)).status_code == 201
    w.trial_ends_at = datetime.now(UTC) - timedelta(days=1)
    await db.commit()
    await fund(db, ws, 10)
    assert (await client.post("/api/v1/campaigns", json=body)).status_code == 201


async def test_estimate_shows_the_credit_ceiling(metered, db, owner, client):
    metered_client, ws = metered
    await fund(db, ws, 30)
    body = campaign_body("G", rows("theta", with_phone=1), max_companies=25)
    est = (await metered_client.post("/api/v1/campaigns/estimate", json=body)).json()
    assert est["credits_max"] == 25 and est["credit_balance"] == 30
    # Exempt workspaces (the operator's own) are not metered.
    est = (await client.post("/api/v1/campaigns/estimate", json=body)).json()
    assert est["credits_max"] == 0 and est["credit_balance"] is None


async def test_ledger_rejects_bad_amounts_and_overdraft(metered, db):
    _, ws = metered
    ws_id = ws.id
    with pytest.raises(ValueError):
        await credit_svc.grant(db, ws_id, 0, CreditKind.PURCHASE)
    with pytest.raises(credit_svc.InsufficientCredits):
        await credit_svc.adjust(db, ws_id, -1)
    await db.rollback()
    tx = await credit_svc.adjust(db, ws_id, 3, note="goodwill")
    await db.commit()
    assert tx.balance_after == 3 and await balance(db, ws_id) == 3


async def test_reanalyze_needs_credits_on_a_metered_workspace(metered, db, dispatched):
    client, ws = metered
    await fund(db, ws, 3)
    camp = await start(client, campaign_body("H", rows("iota", with_phone=1)))
    assert await run_latest(camp["id"]) == "completed"
    lead = await db.scalar(select(CampaignLead).where(CampaignLead.campaign_id == uuid.UUID(camp["id"])))
    assert (await client.post(f"/api/v1/leads/{lead.business_id}/reanalyze")).status_code == 200
    await credit_svc.adjust(db, ws.id, -(await balance(db, ws)))
    await db.commit()
    r = await client.post(f"/api/v1/leads/{lead.business_id}/reanalyze")
    assert r.status_code == 402 and r.json()["error"]["code"] == "insufficient_credits"
