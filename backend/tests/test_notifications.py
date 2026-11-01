"""Scenario 10: Telegram completion notification with numbers taken from campaign records."""

import json
import uuid

import httpx
import respx

from tests.conftest import run_latest


async def test_completion_notification_uses_real_counts(client, dispatched, monkeypatch, db):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    from app.core.config import get_settings

    get_settings.cache_clear()
    try:
        r = await client.post(
            "/api/v1/campaigns",
            json={
                "name": "Notify",
                "country": "SA",
                "city": "Riyadh",
                "industry": "dental_clinics",
                "sources": [{"provider_key": "demo"}],
                "settings": {"target_count": 6, "max_companies": 6},
                "start": True,
            },
        )
        camp = r.json()
        from app.models import Campaign

        c = await db.get(Campaign, uuid.UUID(camp["id"]))
        c.telegram_chat_id = 4242
        await db.commit()
        with respx.mock(assert_all_called=False) as mock:
            route = mock.post(url__regex=r"https://api\.telegram\.org/bot123:abc/.*").mock(
                return_value=httpx.Response(200, json={"ok": True, "result": {"message_id": 7}})
            )
            assert await run_latest(camp["id"]) == "completed"
        payloads = [json.loads(call.request.content) for call in route.calls]
        final = [p for p in payloads if "Search completed" in p.get("text", "")]
        assert final, payloads
        detail = (await client.get(f"/api/v1/campaigns/{camp['id']}")).json()["stats"]
        text = final[-1]["text"]
        assert final[-1]["parse_mode"] == "HTML"
        assert f"Target: {detail['target']}" in text
        assert f"Found: {detail['unique_leads']}" in text
        assert f"Qualified: {detail['qualified']}" in text
        assert f"verified: {detail['verified_emails']}" in text
        assert "Credits used" not in text  # demo searches are free
        assert "Best leads" in text and "/100" in text
        assert "$" not in text
        assert final[-1]["chat_id"] == 4242
        buttons = [b["text"] for row in final[-1]["reply_markup"]["inline_keyboard"] for b in row]
        assert any("CSV" in b for b in buttons) and any("Best leads" in b for b in buttons)
    finally:
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN")
        get_settings.cache_clear()
