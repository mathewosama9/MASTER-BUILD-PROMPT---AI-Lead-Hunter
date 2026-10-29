"""Telegram command and callback tests: real aiogram Dispatcher, recorded Bot API calls, mocked backend."""
import json
from datetime import datetime
from typing import Any

import httpx
import pytest
from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import AnswerCallbackQuery, SendMessage, TelegramMethod
from aiogram.types import CallbackQuery, Chat, Message, Update, User

from bot import middleware
from bot.app import build_dispatcher
from bot.services.api import BackendClient

LINKED = 1001
PENDING = 2002


class RecordingSession(BaseSession):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list[TelegramMethod] = []

    async def make_request(self, bot: Bot, method: TelegramMethod[Any], timeout: int | None = None) -> Any:
        self.calls.append(method)
        if isinstance(method, SendMessage):
            return Message(message_id=len(self.calls), date=datetime.now(), text=method.text,
                           chat=Chat(id=method.chat_id, type="private"))
        return True

    async def close(self) -> None:  # pragma: no cover
        pass

    async def stream_content(self, *a, **k):  # pragma: no cover
        yield b""

    def texts(self) -> list[str]:
        return [c.text for c in self.calls if isinstance(c, SendMessage)]


META = {"demo_mode": True,
        "countries": [{"code": "SA", "name_en": "Saudi Arabia", "name_ar": "السعودية",
                       "cities": [{"en": "Riyadh", "ar": "الرياض"}]}],
        "industries": [{"key": "dental_clinics", "en": "Dental Clinics", "ar": "عيادات الأسنان"}]}
CAMPAIGN = {"id": "c0ffee00-0000-0000-0000-000000000001", "name": "Dental", "status": "queued", "stage": "created",
            "country": "SA", "city": "Riyadh", "industry": "dental_clinics", "is_demo": True,
            "settings": {"target_count": 20}, "stats": {"target": 20}, "cost_discovery": 0, "cost_ai": 0,
            "last_error": None}


class Backend:
    def __init__(self) -> None:
        self.created: list[dict] = []
        self.actions: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/api/v1")
        uid = request.headers.get("x-telegram-user-id")
        assert request.headers.get("x-service-token") == "svc"
        if path == "/telegram/whoami":
            if uid == str(LINKED):
                return httpx.Response(200, json={"user": "a@b.c", "role": "owner", "demo_mode": True})
            return httpx.Response(403, json={"error": {"message": "not linked"}})
        if path == "/telegram/status":
            status = "pending" if request.url.params["telegram_user_id"] == str(PENDING) else "unlinked"
            return httpx.Response(200, json={"status": status})
        if path == "/telegram/link":
            return httpx.Response(200, json={"status": "approved"})
        if path == "/meta":
            return httpx.Response(200, json=META)
        if path == "/providers":
            return httpx.Response(200, json=[{"key": "demo", "status": "connected"},
                                             {"key": "brave", "status": "requires_api_key",
                                              "status_detail": "Set BRAVE_API_KEY"}])
        if path == "/campaigns" and request.method == "POST":
            self.created.append(json.loads(request.content))
            return httpx.Response(201, json=CAMPAIGN)
        if path == "/campaigns" and request.method == "GET":
            return httpx.Response(200, json={"items": [CAMPAIGN], "total": 1})
        if path.endswith("/pause"):
            self.actions.append("pause")
            return httpx.Response(200, json={**CAMPAIGN, "status": "paused"})
        return httpx.Response(404, json={"error": {"message": "nope"}})


_DP = None


@pytest.fixture
def env(monkeypatch):
    global _DP
    middleware._cache.clear()
    backend = Backend()
    api = BackendClient(base_url="http://api/api/v1", service_token="svc",
                        transport=httpx.MockTransport(backend.handler))
    session = RecordingSession()
    bot = Bot(token="42:TEST", session=session)
    if _DP is None:  # aiogram routers can be attached to a single dispatcher per process
        _DP = build_dispatcher(api)
    _DP.workflow_data["auth"].api = api
    return _DP, bot, session, backend


_uid = iter(range(1, 10_000))


def msg(user_id: int, text: str) -> Update:
    user = User(id=user_id, is_bot=False, first_name="T", language_code="en")
    return Update(update_id=next(_uid), message=Message(message_id=next(_uid), date=datetime.now(), text=text,
                                                        chat=Chat(id=user_id, type="private"), from_user=user))


def cb(user_id: int, data: str) -> Update:
    user = User(id=user_id, is_bot=False, first_name="T", language_code="en")
    m = Message(message_id=1, date=datetime.now(), text="x", chat=Chat(id=user_id, type="private"))
    return Update(update_id=next(_uid), callback_query=CallbackQuery(id=str(next(_uid)), from_user=user,
                                                                     chat_instance="i", message=m, data=data))


async def feed(dp, bot, update):
    await dp.feed_update(bot, update)


async def test_unlinked_user_is_told_to_link(env):
    dp, bot, session, _ = env
    await feed(dp, bot, msg(5555, "/start"))
    assert "not linked" in session.texts()[-1]


async def test_pending_user_sees_pending(env):
    dp, bot, session, _ = env
    await feed(dp, bot, msg(PENDING, "/start"))
    assert "approval" in session.texts()[-1]


async def test_link_command_reaches_backend_without_auth(env):
    dp, bot, session, _ = env
    await feed(dp, bot, msg(5555, "/link ABCD2345"))
    assert "linked" in session.texts()[-1].lower()


async def test_start_shows_main_menu_with_demo_banner(env):
    dp, bot, session, _ = env
    await feed(dp, bot, msg(LINKED, "/start"))
    sent = [c for c in session.calls if isinstance(c, SendMessage)][-1]
    assert "Welcome" in sent.text and "DEMO MODE" in sent.text
    labels = [b.text for row in sent.reply_markup.inline_keyboard for b in row]
    for expected in ("New Campaign", "My Campaigns", "Top Leads", "Campaign Statistics", "Export Leads", "Help"):
        assert any(expected in label for label in labels)


async def test_full_wizard_creates_campaign_through_backend(env):
    dp, bot, session, backend = env
    for update in (cb(LINKED, "m:new"), cb(LINKED, "w:country:SA"), cb(LINKED, "w:city:0"),
                   cb(LINKED, "w:ind:dental_clinics")):
        await feed(dp, bot, update)
    # Unavailable providers cannot be selected.
    await feed(dp, bot, cb(LINKED, "w:src:brave"))
    alert = [c for c in session.calls if isinstance(c, AnswerCallbackQuery)][-1]
    assert alert.show_alert and "BRAVE_API_KEY" in alert.text
    for update in (cb(LINKED, "w:src:demo"), cb(LINKED, "w:src:done"), cb(LINKED, "w:count:custom"),
                   msg(LINKED, "35"), cb(LINKED, "w:ai:yes")):
        await feed(dp, bot, update)
    assert "Confirm" in session.texts()[-1] and "Target: 35" in session.texts()[-1]
    await feed(dp, bot, cb(LINKED, "w:go"))
    assert len(backend.created) == 1
    body = backend.created[0]
    assert body["country"] == "SA" and body["city"] == "Riyadh" and body["industry"] == "dental_clinics"
    assert body["sources"] == [{"provider_key": "demo"}]
    assert body["settings"]["target_count"] == 35 and body["settings"]["ai_analysis"] is True
    assert body["start"] is True
    assert "Research started" in session.texts()[-1]


async def test_invalid_custom_count_is_rejected(env):
    dp, bot, session, _ = env
    for update in (cb(LINKED, "m:new"), cb(LINKED, "w:country:SA"), cb(LINKED, "w:city:skip"),
                   cb(LINKED, "w:ind:dental_clinics"), cb(LINKED, "w:src:demo"), cb(LINKED, "w:src:done"),
                   cb(LINKED, "w:count:custom"), msg(LINKED, "9999")):
        await feed(dp, bot, update)
    assert "between 1 and 500" in session.texts()[-1]


async def test_pause_button_calls_backend(env):
    dp, bot, session, backend = env
    await feed(dp, bot, cb(LINKED, f"c:pause:{CAMPAIGN['id']}"))
    assert backend.actions == ["pause"]


async def test_group_chats_are_ignored(env):
    dp, bot, session, _ = env
    user = User(id=LINKED, is_bot=False, first_name="T")
    update = Update(update_id=next(_uid), message=Message(message_id=1, date=datetime.now(), text="/start",
                                                          chat=Chat(id=-100, type="group"), from_user=user))
    await feed(dp, bot, update)
    assert session.texts() == []
