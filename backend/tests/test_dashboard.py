"""Overview stats: customers see pipeline, next actions and a getting-started checklist, but never provider costs."""

from app.models import Business, BusinessContact
from tests.conftest import login, make_user


async def test_overview_for_customer_hides_costs_and_lists_next_actions(app, db):
    user, ws = await make_user(db)
    hot = Business(
        workspace_id=ws.id, name="Smile Clinic", normalized_name="smile clinic", latest_score=91, contact_count=1
    )
    done = Business(
        workspace_id=ws.id,
        name="Old Lead",
        normalized_name="old lead",
        latest_score=95,
        contact_count=1,
        crm_status="contacted",
    )
    silent = Business(workspace_id=ws.id, name="No Phone", normalized_name="no phone", latest_score=99)
    db.add_all([hot, done, silent])
    await db.flush()
    db.add_all(
        [
            BusinessContact(
                business_id=hot.id,
                type="whatsapp",
                value="+966500000001",
                normalized_value="966500000001",
                source_provider="website",
            ),
            BusinessContact(
                business_id=done.id,
                type="phone",
                value="+966500000002",
                normalized_value="966500000002",
                source_provider="website",
            ),
        ]
    )
    await db.commit()
    c = await login(app, user.email)
    try:
        s = (await c.get("/api/v1/dashboard/stats")).json()
    finally:
        await c.aclose()

    assert "ai_cost_usd" not in s["totals"] and "discovery_cost_usd" not in s["totals"]
    assert s["by_source"] == []
    assert [a["name"] for a in s["next_actions"]] == ["Smile Clinic"]
    assert s["next_actions"][0]["whatsapp"] == "+966500000001"
    assert s["pipeline"]["new"] == 2 and s["pipeline"]["contacted"] == 1
    assert s["totals"]["reached"] == 1
    assert s["checklist"] == {
        "email_verified": True,
        "profile": False,
        "telegram": False,
        "campaign": False,
        "contacted": True,
    }
    assert s["period"]["new"] == {"current": 3, "previous": 0}


async def test_overview_for_platform_admin_includes_costs(app, db):
    user, _ = await make_user(db)
    user.is_superuser = True
    await db.commit()
    c = await login(app, user.email)
    try:
        s = (await c.get("/api/v1/dashboard/stats")).json()
    finally:
        await c.aclose()
    assert "ai_cost_usd" in s["totals"]
