"""API integration tests covering the critical scenarios from the spec, with demo fixtures."""

import uuid

import httpx
from sqlalchemy import select

from app.models import Business, BusinessContact, CampaignLead, JobEvent
from app.models.enums import Role
from tests.conftest import login, make_user, run_latest

DEMO = {
    "name": "Riyadh Dental (Demo)",
    "country": "SA",
    "city": "Riyadh",
    "industry": "dental_clinics",
    "services": ["appointment_automation", "whatsapp_automation"],
    "sources": [{"provider_key": "demo"}],
    "settings": {"target_count": 8, "max_companies": 10, "email_verification": True, "min_score": 40},
}


async def create(client, body=None, start=True):
    r = await client.post("/api/v1/campaigns", json={**(body or DEMO), "start": start})
    assert r.status_code == 201, r.text
    return r.json()


async def test_health_and_openapi(app):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        assert (await c.get("/api/v1/health")).status_code == 200
        assert "/api/v1/campaigns" in (await c.get("/api/openapi.json")).json()["paths"]


async def test_unauthenticated_requests_are_rejected(app):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/v1/campaigns")
        assert r.status_code == 401
        assert r.json()["error"]["code"] == "unauthorized"
        bad = await c.post("/api/v1/auth/login", json={"email": "nobody@example.com", "password": "x"})
        assert bad.status_code == 401


async def test_csrf_required_for_cookie_mutations(app, owner):
    c = await login(app, owner[0].email)
    del c.headers["x-csrf-token"]
    r = await c.post("/api/v1/campaigns", json=DEMO)
    assert r.status_code == 403
    await c.aclose()


async def test_full_demo_campaign_flow(client, dispatched, db):
    # 1. create from dashboard
    camp = await create(client)
    assert camp["status"] == "queued" and camp["is_demo"]
    assert len(dispatched) == 1
    # 2-6. discovery, persistence, enrichment, analysis, scoring
    assert await run_latest(camp["id"]) == "completed"
    detail = (await client.get(f"/api/v1/campaigns/{camp['id']}")).json()
    s = detail["stats"]
    assert s["target"] == 8
    assert s["unique_leads"] == 10  # max_companies cap; target vs actual reported separately
    assert s["discovered"] >= s["unique_leads"]
    assert s["scored"] == s["unique_leads"]
    assert s["progress"]["percent"] == 100.0
    assert s["ai_provider"] == "demo"
    # 7. results visible in dashboard
    leads = (await client.get("/api/v1/leads", params={"campaign_id": camp["id"], "sort": "score"})).json()
    assert leads["total"] == 10
    scores = [x["latest_score"] for x in leads["items"]]
    assert scores == sorted(scores, reverse=True)
    assert all(x["is_demo"] for x in leads["items"])
    lead = (await client.get(f"/api/v1/leads/{leads['items'][0]['id']}")).json()
    assert lead["score"]["factors"] and lead["score"]["scoring_version"]
    assert lead["assessment"]["provider"] == "demo"
    assert lead["evidence"] and lead["sources"]
    # Demo contacts carry the demo restriction label.
    assert all("DEMO" in (c["usage_restrictions"] or "") for c in lead["contacts"])
    stats = (await client.get("/api/v1/dashboard/stats")).json()
    assert stats["totals"]["businesses"] >= 10
    assert sum(b["count"] for b in stats["score_distribution"]) >= 10
    # 8. export CSV (UTF-8 BOM so Arabic renders in Excel)
    r = await client.get("/api/v1/exports/leads", params={"campaign_id": camp["id"], "format": "csv"})
    assert r.status_code == 200
    assert r.content.startswith("﻿".encode())
    text = r.content.decode("utf-8-sig")
    assert text.splitlines()[0].startswith("Company,Industry")
    assert len(text.strip().splitlines()) == 11
    x = await client.get(f"/api/v1/exports/campaigns/{camp['id']}", params={"format": "xlsx"})
    assert x.status_code == 200 and x.content[:2] == b"PK"
    # events were recorded for every stage
    events = (await client.get(f"/api/v1/campaigns/{camp['id']}/events/history")).json()
    stages = {e["stage"] for e in events}
    assert {"discovery", "deduplication", "lead_scoring"} <= stages


async def test_reanalyze_touches_one_lead_and_respects_campaign_state(client, dispatched, db):
    from app.models import Campaign, LeadAssessment
    from app.models.enums import CampaignStatus

    camp = await create(client)
    assert await run_latest(camp["id"]) == "completed"
    cid = uuid.UUID(camp["id"])
    leads = (await db.scalars(select(CampaignLead).where(CampaignLead.campaign_id == cid))).all()
    target, other = leads[0], leads[1]
    # Another lead left pending (e.g. a paused run) must not be analysed by a single-lead request.
    other.analyzed = other.scored = False
    await db.commit()

    async def assessments(business_id):
        q = select(LeadAssessment.id).where(LeadAssessment.business_id == business_id)
        return len((await db.scalars(q)).all())

    before_target, before_other = await assessments(target.business_id), await assessments(other.business_id)
    r = await client.post(f"/api/v1/leads/{target.business_id}/reanalyze")
    assert r.status_code == 200, r.text
    assert await assessments(target.business_id) == before_target + 1
    assert await assessments(other.business_id) == before_other
    await db.refresh(other)
    assert not other.analyzed

    campaign = await db.get(Campaign, cid)
    for status in (CampaignStatus.ENRICHING, CampaignStatus.CANCELLED):
        campaign.status = status
        await db.commit()
        assert (await client.post(f"/api/v1/leads/{target.business_id}/reanalyze")).status_code == 409

    # The campaign budget still applies.
    campaign.status = CampaignStatus.COMPLETED
    campaign.settings = {**campaign.settings, "max_budget_usd": 0}
    await db.commit()
    r = await client.post(f"/api/v1/leads/{target.business_id}/reanalyze")
    assert r.status_code == 409 and "budget" in r.text
    assert await assessments(target.business_id) == before_target + 1


async def test_businesses_without_contacts_are_kept(client, dispatched, db):
    camp = await create(client, {**DEMO, "settings": {**DEMO["settings"], "max_companies": 30, "target_count": 30}})
    await run_latest(camp["id"])
    rows = (
        await client.get("/api/v1/leads", params={"campaign_id": camp["id"], "has_contact": False, "page_size": 100})
    ).json()
    for r in rows["items"]:
        assert r["contact_count"] == 0
        assert not r["outreach_eligible"]
    total = (await client.get("/api/v1/leads", params={"campaign_id": camp["id"]})).json()["total"]
    assert total == 30


async def test_duplicates_across_campaigns_share_one_business(client, dispatched, db):
    a = await create(client)
    await run_latest(a["id"])
    b = await create(client)
    await run_latest(b["id"])
    b_leads = (await db.scalars(select(CampaignLead).where(CampaignLead.campaign_id == uuid.UUID(b["id"])))).all()
    a_ids = set(
        (await db.scalars(select(CampaignLead.business_id).where(CampaignLead.campaign_id == uuid.UUID(a["id"])))).all()
    )
    # Same deterministic demo seed differs per campaign, but any shared domain must reuse the business row.
    for lead in b_leads:
        if lead.business_id in a_ids:
            assert lead.pre_existing
    ws_id = (await db.get(Business, b_leads[0].business_id)).workspace_id
    domains = (
        await db.scalars(
            select(Business.normalized_domain).where(
                Business.workspace_id == ws_id, Business.normalized_domain.is_not(None)
            )
        )
    ).all()
    assert len(domains) == len(set(domains))


async def test_exclude_duplicates_setting(client, dispatched, db):
    a = await create(client)
    await run_latest(a["id"])
    body = {**DEMO, "settings": {**DEMO["settings"], "exclude_duplicates": True}}
    b = await create(client, body)
    await run_latest(b["id"])
    b_detail = (await client.get(f"/api/v1/campaigns/{b['id']}")).json()
    leads = (await db.scalars(select(CampaignLead).where(CampaignLead.campaign_id == uuid.UUID(b["id"])))).all()
    assert all(not lead.pre_existing for lead in leads)
    assert b_detail["stats"]["duplicates_removed"] >= 0


async def test_pause_resume_and_cancel(client, dispatched, db):
    camp = await create(client)
    r = await client.post(f"/api/v1/campaigns/{camp['id']}/pause")
    assert r.status_code == 200 and r.json()["status"] == "paused"
    # Worker picks up the queued run but sees the pause and exits without work.
    assert await run_latest(camp["id"]) == "paused"
    r = await client.post(f"/api/v1/campaigns/{camp['id']}/resume")
    assert r.json()["status"] == "queued"
    assert len(dispatched) == 2
    assert await run_latest(camp["id"]) == "completed"
    # Cannot cancel a finished campaign; can retry? only failed/partial
    assert (await client.post(f"/api/v1/campaigns/{camp['id']}/cancel")).status_code == 409
    other = await create(client)
    r = await client.post(f"/api/v1/campaigns/{other['id']}/cancel")
    assert r.json()["status"] == "cancelled"
    assert await run_latest(other["id"]) == "cancelled"
    dup = await client.post(f"/api/v1/campaigns/{other['id']}/duplicate")
    assert dup.status_code == 201 and dup.json()["status"] == "draft"


async def test_pause_mid_run_and_resume_from_checkpoint(client, dispatched, db, monkeypatch):
    from app.research import pipeline

    camp = await create(client)
    original = pipeline.CampaignPipeline.stage_analysis

    async def pause_then_analyze(self):
        from app.models import Campaign

        c = await self.db.get(Campaign, self.campaign.id)
        c.status = "paused"
        await self.db.commit()
        return await original(self)

    monkeypatch.setattr(pipeline.CampaignPipeline, "stage_analysis", pause_then_analyze)
    assert await run_latest(camp["id"]) == "paused"
    monkeypatch.setattr(pipeline.CampaignPipeline, "stage_analysis", original)
    detail = (await client.get(f"/api/v1/campaigns/{camp['id']}")).json()
    enriched_before = detail["stats"]["enriched"]
    assert enriched_before == detail["stats"]["unique_leads"]
    await client.post(f"/api/v1/campaigns/{camp['id']}/resume")
    assert await run_latest(camp["id"]) == "completed"
    after = (await client.get(f"/api/v1/campaigns/{camp['id']}")).json()["stats"]
    assert after["unique_leads"] == detail["stats"]["unique_leads"]  # no re-discovery after resume
    assert after["scored"] == after["unique_leads"]


async def test_real_campaign_with_missing_credentials_is_honest(client, dispatched, db):
    body = {**DEMO, "name": "Real", "sources": [{"provider_key": "brave"}, {"provider_key": "hunter"}]}
    camp = await create(client, body)
    assert not camp["is_demo"]
    status = await run_latest(camp["id"])
    assert status in ("partially_completed", "failed")
    detail = (await client.get(f"/api/v1/campaigns/{camp['id']}")).json()
    assert detail["stats"]["unique_leads"] == 0  # nothing fabricated
    assert {s["status"] for s in detail["sources"]} == {"skipped"}
    events = (await client.get(f"/api/v1/campaigns/{camp['id']}/events/history")).json()
    assert any(e["event_type"] == "provider_unavailable" for e in events)


async def test_demo_provider_cannot_be_used_in_real_campaign(client, dispatched):
    body = {**DEMO, "is_demo": False, "sources": [{"provider_key": "demo"}]}
    r = await client.post("/api/v1/campaigns", json=body)
    assert r.status_code == 409


async def test_rate_limited_provider_is_reported_and_partial(client, dispatched, db, monkeypatch):
    monkeypatch.setattr("app.research.pipeline.MAX_PROVIDER_ATTEMPTS", 2)
    body = {**DEMO, "research_spec": {"demo_options": {"simulate_rate_limit": True}}}
    camp = await create(client, body)
    status = await run_latest(camp["id"])
    assert status == "failed"
    events = (await db.scalars(select(JobEvent).where(JobEvent.campaign_id == uuid.UUID(camp["id"])))).all()
    assert sum(1 for e in events if e.event_type == "rate_limited") == 2
    assert any(e.event_type == "provider_failed" for e in events)
    # retry after the "limit" clears
    from app.models import Campaign

    c = await db.get(Campaign, uuid.UUID(camp["id"]))
    c.research_spec = {}
    await db.commit()
    r = await client.post(f"/api/v1/campaigns/{camp['id']}/retry")
    assert r.status_code == 200
    assert await run_latest(camp["id"]) == "completed"


async def test_suppression_blocks_outreach_across_campaigns(client, dispatched, db):
    a = await create(client)
    await run_latest(a["id"])
    leads = (await client.get("/api/v1/leads", params={"campaign_id": a["id"], "has_contact": True})).json()
    target = next(x for x in leads["items"] if x["outreach_eligible"])
    r = await client.patch(f"/api/v1/leads/{target['id']}", json={"crm_status": "do_not_contact"})
    assert r.status_code == 200
    detail = (await client.get(f"/api/v1/leads/{target['id']}")).json()
    assert detail["suppressed"] and not detail["outreach_eligible"]
    assert (await client.post(f"/api/v1/leads/{target['id']}/pitch", json={})).status_code == 409
    # The business re-enters through another campaign but stays suppressed.
    b = await create(client)
    await run_latest(b["id"])
    again = (await client.get(f"/api/v1/leads/{target['id']}")).json()
    assert again["business"]["crm_status"] == "do_not_contact"
    assert not again["outreach_eligible"]
    sup = (await client.get("/api/v1/suppression")).json()
    assert any(e["kind"] == "domain" for e in sup)


async def test_email_suppression_marks_contacts(client, dispatched, db):
    a = await create(client)
    await run_latest(a["id"])
    contact = await db.scalar(
        select(BusinessContact)
        .join(CampaignLead, CampaignLead.business_id == BusinessContact.business_id)
        .where(CampaignLead.campaign_id == uuid.UUID(a["id"]), BusinessContact.type == "email")
        .limit(1)
    )
    r = await client.post("/api/v1/suppression", json={"kind": "email", "value": contact.normalized_value})
    assert r.status_code == 201
    await db.refresh(contact)
    assert contact.is_suppressed


async def test_pitch_generation_creates_draft_only(client, dispatched, db):
    a = await create(client)
    await run_latest(a["id"])
    lead = (await client.get("/api/v1/leads", params={"campaign_id": a["id"]})).json()["items"][0]
    r = await client.post(f"/api/v1/leads/{lead['id']}/pitch", json={"language": "ar"})
    assert r.status_code == 201
    d = r.json()
    assert d["provider"] == "demo-template"
    assert d["email_body"] and "إلغاء" in d["email_body"]  # opt-out line included


async def test_workspace_isolation(app, client, dispatched, db):
    camp = await create(client)
    await run_latest(camp["id"])
    lead_id = (await client.get("/api/v1/leads")).json()["items"][0]["id"]
    other_user, _ = await make_user(db)
    other = await login(app, other_user.email)
    assert (await other.get(f"/api/v1/campaigns/{camp['id']}")).status_code == 404
    assert (await other.get(f"/api/v1/leads/{lead_id}")).status_code == 404
    assert (await other.get("/api/v1/leads")).json()["total"] == 0
    assert (await other.post(f"/api/v1/campaigns/{camp['id']}/cancel")).status_code == 404
    await other.aclose()


async def test_viewer_cannot_mutate(app, owner, db, dispatched):
    viewer, _ = await make_user(db, role=Role.VIEWER, workspace=owner[1])
    c = await login(app, viewer.email)
    assert (await c.post("/api/v1/campaigns", json=DEMO)).status_code == 403
    assert (await c.put("/api/v1/providers/brave", json={"enabled": False})).status_code == 403
    assert (await c.get("/api/v1/campaigns")).status_code == 200
    await c.aclose()


async def test_admin_cannot_modify_an_owner(app, owner, db):
    admin, _ = await make_user(db, role=Role.ADMIN, workspace=owner[1])
    member, _ = await make_user(db, role=Role.ANALYST, workspace=owner[1])
    c = await login(app, admin.email)
    target = f"/api/v1/users/{owner[0].id}"
    for body in ({"is_active": False}, {"full_name": "Hijacked"}, {"role": "analyst"}):
        assert (await c.patch(target, json=body)).status_code == 409, body
    assert (await c.patch(f"/api/v1/users/{member.id}", json={"role": "owner"})).status_code == 409
    # Admins still manage non-owners.
    r = await c.patch(f"/api/v1/users/{member.id}", json={"full_name": "Renamed", "is_active": False})
    assert r.status_code == 200 and r.json()["user"]["full_name"] == "Renamed"
    await c.aclose()
    await db.refresh(owner[0])
    assert owner[0].is_active and owner[0].full_name == "Test User"
    # The owner can still edit themselves.
    o = await login(app, owner[0].email)
    assert (await o.patch(target, json={"full_name": "Owner"})).status_code == 200
    await o.aclose()


async def test_customers_cannot_manage_provider_keys_or_see_them(client):
    assert (await client.put("/api/v1/providers/brave", json={"credentials": {"api_key": "x" * 20}})).status_code == 403
    assert (await client.get("/api/v1/providers/sessions")).status_code == 403
    brave = next(p for p in (await client.get("/api/v1/providers")).json() if p["key"] == "brave")
    assert brave["credentials_masked"] == {} and brave["usage_month"]["cost_usd"] == 0.0


async def test_platform_keys_apply_to_every_workspace(app, db, client, platform_admin):
    r = await client.put("/api/v1/providers/brave", json={"credentials": {"api_key": "platform-brave-key-5678"}})
    assert r.status_code == 200 and r.json()["credential_source"] == "platform"
    customer, _ = await make_user(db)
    c = await login(app, customer.email)
    brave = next(p for p in (await c.get("/api/v1/providers")).json() if p["key"] == "brave")
    await c.aclose()
    assert brave["status"] == "connected" and brave["credentials_masked"] == {}


async def test_provider_credentials_are_never_returned(client, platform_admin):
    r = await client.put("/api/v1/providers/brave", json={"credentials": {"api_key": "super-secret-brave-key-1234"}})
    assert r.status_code == 200
    body = (await client.get("/api/v1/providers")).text
    assert "super-secret-brave-key" not in body
    brave = next(p for p in (await client.get("/api/v1/providers")).json() if p["key"] == "brave")
    assert brave["status"] == "connected"
    assert brave["credentials_masked"]["api_key"].endswith("1234")
    demo = next(p for p in (await client.get("/api/v1/providers")).json() if p["key"] == "demo")
    assert demo["status"] == "connected"
    fb = next(p for p in (await client.get("/api/v1/providers")).json() if p["key"] == "facebook")
    assert fb["status"] == "unsupported"


async def test_manual_lead_and_validation(client):
    r = await client.post(
        "/api/v1/leads",
        json={
            "name": "مطعم الواحة",
            "website_url": "https://oasis-food.sa",
            "country": "SA",
            "email": "info@oasis-food.sa",
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["name"] == "مطعم الواحة"
    dup = await client.post("/api/v1/leads", json={"name": "Oasis", "website_url": "https://www.oasis-food.sa/x"})
    assert dup.status_code == 409
    bad = await client.post("/api/v1/campaigns", json={**DEMO, "country": "SAU"})
    assert bad.status_code == 422


async def test_parse_spec_without_ai_uses_rule_based(client):
    r = await client.post(
        "/api/v1/campaigns/parse-spec",
        json={"text": "Private dental clinics in Riyadh that may benefit from appointment automation"},
    )
    spec = r.json()
    assert spec["parser"] == "rule_based"
    assert spec["industry"] == "dental_clinics" and spec["country"] == "SA" and spec["city"] == "Riyadh"


async def test_export_with_arabic_campaign_name(client):
    r = await client.post(
        "/api/v1/campaigns",
        json={
            "name": "عيادات أسنان · الرياض",
            "country": "SA",
            "industry": "dental_clinics",
            "sources": [{"provider_key": "demo"}],
        },
    )
    cid = r.json()["id"]
    for fmt in ("csv", "xlsx"):
        res = await client.get(f"/api/v1/exports/campaigns/{cid}", params={"format": fmt})
        assert res.status_code == 200, res.text
        disposition = res.headers["content-disposition"]
        assert "filename*=UTF-8''" in disposition and "%D8%B9" in disposition  # "ع" percent-encoded
