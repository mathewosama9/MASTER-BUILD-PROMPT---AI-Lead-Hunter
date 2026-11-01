"""Telegram linking and service-token access, as used by the bot."""

import httpx

from app.models.enums import Role
from tests.conftest import login, make_user, run_latest

SVC = {"x-service-token": "test-service-token"}


async def bot_client(app, tg_id: int) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://t", headers={**SVC, "x-telegram-user-id": str(tg_id)}
    )


async def link(app, client, tg_id: int) -> dict:
    code = (await client.post("/api/v1/telegram/link-code")).json()["code"]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t", headers=SVC) as c:
        r = await c.post("/api/v1/telegram/link", json={"code": code, "telegram_user_id": tg_id, "chat_id": tg_id})
        assert r.status_code == 200, r.text
        # one-time code
        again = await c.post("/api/v1/telegram/link", json={"code": code, "telegram_user_id": tg_id, "chat_id": tg_id})
        assert again.status_code == 401
        return r.json()


async def test_unlinked_and_bad_token_rejected(app):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/v1/telegram/whoami", headers={"x-service-token": "wrong", "x-telegram-user-id": "1"})
        assert r.status_code == 401
        r = await c.get("/api/v1/telegram/whoami", headers={**SVC, "x-telegram-user-id": "999"})
        assert r.status_code == 403


async def test_owner_link_is_auto_approved_and_can_run_campaign(app, client, dispatched):
    assert (await link(app, client, 111))["status"] == "approved"
    bot = await bot_client(app, 111)
    assert (await bot.get("/api/v1/telegram/whoami")).status_code == 200
    r = await bot.post(
        "/api/v1/campaigns",
        json={
            "name": "TG demo",
            "country": "AE",
            "city": "Dubai",
            "industry": "real_estate",
            "sources": [{"provider_key": "demo"}],
            "settings": {"target_count": 5, "max_companies": 5},
            "start": True,
        },
    )
    assert r.status_code == 201, r.text
    camp = r.json()
    assert camp["origin"] == "telegram"
    assert await run_latest(camp["id"]) == "completed"
    detail = (await bot.get(f"/api/v1/campaigns/{camp['id']}")).json()
    assert detail["stats"]["unique_leads"] == 5
    top = (await bot.get("/api/v1/leads", params={"campaign_id": camp["id"], "page_size": 10})).json()
    assert top["total"] == 5
    csv = await bot.get("/api/v1/exports/campaigns/" + camp["id"], params={"format": "csv"})
    assert csv.status_code == 200
    await bot.aclose()


async def test_analyst_link_requires_admin_approval(app, owner, db, dispatched):
    analyst, _ = await make_user(db, role=Role.ANALYST, workspace=owner[1])
    ac = await login(app, analyst.email)
    assert (await link(app, ac, 222))["status"] == "pending"
    bot = await bot_client(app, 222)
    assert (await bot.get("/api/v1/telegram/whoami")).status_code == 403
    admin = await login(app, owner[0].email)
    accounts = (await admin.get("/api/v1/telegram/accounts")).json()
    acc = next(a for a in accounts if a["telegram_user_id"] == 222)
    assert (await admin.post(f"/api/v1/telegram/accounts/{acc['id']}/approve")).status_code == 200
    assert (await bot.get("/api/v1/telegram/whoami")).status_code == 200
    # Telegram users only see campaigns they created.
    await admin.post(
        "/api/v1/campaigns",
        json={"name": "admin only", "country": "SA", "industry": "education", "sources": [{"provider_key": "demo"}]},
    )
    mine = (await bot.get("/api/v1/campaigns")).json()
    assert all(c["name"] != "admin only" for c in mine["items"])
    # Revocation takes effect immediately.
    await admin.post(f"/api/v1/telegram/accounts/{acc['id']}/revoke")
    assert (await bot.get("/api/v1/telegram/whoami")).status_code == 403
    for c in (ac, admin, bot):
        await c.aclose()


async def test_bot_language_is_saved_and_used_for_notifications(app, client, db):
    from sqlalchemy import select

    from app.models import Campaign, TelegramAccount
    from app.services.notifications import chat_locale, completion_text

    await link(app, client, 333)
    bot = await bot_client(app, 333)
    assert (await bot.post("/api/v1/telegram/locale", json={"locale": "fr"})).status_code == 422
    assert (await bot.post("/api/v1/telegram/locale", json={"locale": "ar"})).status_code == 200
    assert (await bot.get("/api/v1/telegram/whoami")).json()["locale"] == "ar"
    await bot.aclose()

    account = await db.scalar(select(TelegramAccount).where(TelegramAccount.telegram_user_id == 333))
    camp = Campaign(
        name="AR",
        country="SA",
        industry="education",
        telegram_chat_id=account.chat_id,
        status="completed",
        is_demo=False,
        cost_discovery=0.0,
        cost_ai=0.0,
    )
    camp.stats = {"target": 5, "qualified": 3}
    assert await chat_locale(db, camp) == "ar"
    camp.last_error = "Google Maps unavailable (rate_limited)"
    text = completion_text(camp, "ar", credits_used=7, top=[("Bright <Smile>", 82.0)])
    assert "البحث خلص" in text and "مناسبين: 3" in text and "الكريدت المستخدم: 7" in text
    assert "Bright &lt;Smile&gt; — 82/100" in text  # HTML-escaped for parse_mode=HTML
    # Customers never see provider names or USD costs.
    assert "Google" not in text and "$" not in text


async def test_link_code_includes_deep_link(client, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setenv("TELEGRAM_BOT_USERNAME", "@RasdBot")
    get_settings.cache_clear()
    try:
        data = (await client.post("/api/v1/telegram/link-code")).json()
        assert data["bot_username"] == "RasdBot"
        assert data["deep_link"] == f"https://t.me/RasdBot?start={data['code']}"
    finally:
        monkeypatch.delenv("TELEGRAM_BOT_USERNAME")
        get_settings.cache_clear()
    assert (await client.post("/api/v1/telegram/link-code")).json()["deep_link"] is None
