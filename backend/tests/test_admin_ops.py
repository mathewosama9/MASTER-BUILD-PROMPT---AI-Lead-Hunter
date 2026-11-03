"""Platform admin operations: activity log, campaign health, CSV exports and read-only account viewing."""

import csv
import io
from datetime import UTC, datetime, timedelta

from sqlalchemy import update

from app.models import Campaign, CampaignRun
from tests.conftest import login, make_user


def _csv_rows(body: bytes) -> list[list[str]]:
    return list(csv.reader(io.StringIO(body.decode("utf-8-sig"))))


async def test_activity_log_is_platform_wide_and_superuser_only(app, platform_admin, db):
    other, _ = await make_user(db)
    oc = await login(app, other.email)  # writes an auth.login row in another workspace
    admin = await login(app, platform_admin[0].email)
    try:
        assert (await oc.get("/api/v1/admin/audit-logs")).status_code == 403
        r = (await admin.get("/api/v1/admin/audit-logs", params={"action": "auth.login", "q": other.email})).json()
        assert r["total"] >= 1 and {x["action"] for x in r["items"]} == {"auth.login"}
        assert r["items"][0]["user_email"] == other.email and r["items"][0]["workspace_name"]
        assert "auth.login" in (await admin.get("/api/v1/admin/audit-logs/actions")).json()
    finally:
        await oc.aclose()
        await admin.aclose()


async def test_stuck_campaign_is_listed_and_requeued(app, platform_admin, db, dispatched):
    _, ws = await make_user(db)
    camp = Campaign(
        workspace_id=ws.id, name="Stuck search", country="EG", industry="education", status="discovering",
        is_demo=False, cost_discovery=0.0, cost_ai=0.0,
    )  # fmt: skip
    db.add(camp)
    await db.flush()
    run = CampaignRun(campaign_id=camp.id, run_number=1, status="discovering")
    db.add(run)
    await db.commit()
    old = datetime.now(UTC) - timedelta(hours=1)
    await db.execute(update(CampaignRun).where(CampaignRun.id == run.id).values(updated_at=old))
    await db.commit()

    admin = await login(app, platform_admin[0].email)
    try:
        stuck = (await admin.get("/api/v1/admin/campaigns/health", params={"kind": "stuck", "page_size": 100})).json()
        row = next(x for x in stuck["items"] if x["id"] == str(camp.id))
        assert row["stuck"] and row["workspace_name"] == ws.name and row["run_number"] == 1
        assert (await admin.get("/api/v1/admin/campaigns/health/summary")).json()["stuck"] >= 1

        r = await admin.post(f"/api/v1/admin/campaigns/{camp.id}/requeue")
        assert r.status_code == 200, r.text
        assert dispatched[-1] == (camp.id, run.id)
        # A finished campaign cannot be re-queued.
        await db.execute(update(Campaign).where(Campaign.id == camp.id).values(status="completed"))
        await db.commit()
        assert (await admin.post(f"/api/v1/admin/campaigns/{camp.id}/requeue")).status_code == 409
    finally:
        await admin.aclose()


async def test_users_and_payments_csv(app, platform_admin, db):
    other, _ = await make_user(db)
    other.full_name = "=HYPERLINK(evil)"
    await db.commit()
    admin = await login(app, platform_admin[0].email)
    try:
        r = await admin.get("/api/v1/admin/exports/users.csv", params={"q": other.email})
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
        assert "attachment" in r.headers["content-disposition"]
        rows = _csv_rows(r.content)
        assert rows[0][:2] == ["name", "email"] and len(rows) == 2
        assert rows[1][0] == "'=HYPERLINK(evil)" and rows[1][1] == other.email  # formula-safe
        assert rows[1][12] == "none"  # telegram column

        p = await admin.get("/api/v1/admin/exports/payments.csv", params={"status": "approved"})
        assert p.status_code == 200 and _csv_rows(p.content)[0][0] == "date"
        assert (await admin.get("/api/v1/admin/audit-logs", params={"action": "admin.users_exported"})).json()["total"]
    finally:
        await admin.aclose()


async def test_view_customer_account_is_read_only(app, platform_admin, db):
    customer, ws = await make_user(db)
    admin = await login(app, platform_admin[0].email)
    try:
        r = await admin.post(f"/api/v1/admin/users/{customer.id}/impersonate")
        assert r.status_code == 200, r.text
        me = (await admin.get("/api/v1/auth/me")).json()
        assert me["user"]["email"] == customer.email and me["impersonated_by"] == platform_admin[0].email
        assert me["workspace_id"] == str(ws.id)
        assert (await admin.get("/api/v1/campaigns")).status_code == 200

        # Any write is refused while viewing.
        w = await admin.post("/api/v1/telegram/link-code")
        assert w.status_code == 403 and w.json()["error"]["code"] == "impersonation_read_only"
        # Nested viewing is refused (and admin endpoints are out of reach as the customer).
        assert (await admin.post(f"/api/v1/admin/users/{customer.id}/impersonate")).status_code == 403

        # Reads made while viewing are logged as the admin, naming the customer.
        assert (await admin.get("/api/v1/exports/leads", params={"format": "csv"})).status_code == 200
        back = await admin.post("/api/v1/auth/impersonation/stop")
        assert back.status_code == 200 and back.json() == {"user_id": str(customer.id), "signed_out": False}
        me = (await admin.get("/api/v1/auth/me")).json()
        assert me["user"]["email"] == platform_admin[0].email and me["impersonated_by"] is None

        actions = (await admin.get("/api/v1/admin/audit-logs", params={"q": platform_admin[0].email})).json()
        assert {"admin.impersonation_started", "admin.impersonation_stopped"} <= {x["action"] for x in actions["items"]}
        export = next(x for x in actions["items"] if x["action"] == "export.leads")
        assert export["user_email"] == platform_admin[0].email and export["data"]["as_user"] == customer.email
        assert export["workspace_id"] == str(ws.id)

        # Other platform admins cannot be viewed.
        other_admin, _ = await make_user(db)
        other_admin.is_superuser = True
        await db.commit()
        assert (await admin.post(f"/api/v1/admin/users/{other_admin.id}/impersonate")).status_code == 409
    finally:
        await admin.aclose()


async def test_back_to_admin_after_the_view_expired(app, platform_admin, db):
    from app.core.security import create_access_token

    customer, ws = await make_user(db)
    admin = await login(app, platform_admin[0].email)
    try:
        assert (await admin.post(f"/api/v1/admin/users/{customer.id}/impersonate")).status_code == 200
        # The 30-minute customer session ran out.
        expired = create_access_token(customer.id, ws.id, minutes=-1, impersonator=platform_admin[0].id)
        [jar] = [c for c in admin.cookies.jar if c.name == "lh_session"]
        admin.cookies.set("lh_session", expired, domain=jar.domain, path=jar.path)
        assert (await admin.get("/api/v1/auth/me")).status_code == 401
        back = await admin.post("/api/v1/auth/impersonation/stop")
        assert back.json() == {"user_id": str(customer.id), "signed_out": False}
        assert (await admin.get("/api/v1/auth/me")).json()["user"]["email"] == platform_admin[0].email
        # Without the CSRF header the switch is refused.
        assert (await admin.post("/api/v1/auth/impersonation/stop", headers={"x-csrf-token": "x"})).status_code == 403
    finally:
        await admin.aclose()
