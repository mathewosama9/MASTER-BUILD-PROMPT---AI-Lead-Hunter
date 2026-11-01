"""Telegram command and callback tests: real aiogram Dispatcher, recorded Bot API calls, mocked backend."""
import base64
import json
from datetime import datetime
from typing import Any

import httpx
import pytest
from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import AnswerCallbackQuery, EditMessageText, GetFile, SendDocument, SendMessage, TelegramMethod
from aiogram.types import CallbackQuery, Chat, Document, File, Message, Update, User

from bot import middleware
from bot.app import build_dispatcher
from bot.services.api import BackendClient

LINKED = 1001
PENDING = 2002
ARABIC = 3003
NEWBIE = 4004
LEAD_ID = "1ead0000-0000-0000-0000-000000000001"
PKG_ID = "0ac0a6e0-0000-0000-0000-000000000001"
RECEIPT = b"%PDF-1.4 receipt"


class RecordingSession(BaseSession):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list[TelegramMethod] = []

    async def make_request(self, bot: Bot, method: TelegramMethod[Any], timeout: int | None = None) -> Any:
        self.calls.append(method)
        if isinstance(method, (SendMessage, SendDocument)):
            # Bound to the bot, like the responses aiogram builds from real Telegram replies.
            return Message(message_id=100 + len(self.calls), date=datetime.now(), text=getattr(method, "text", None),
                           chat=Chat(id=method.chat_id, type="private")).as_(bot)
        if isinstance(method, GetFile):
            return File(file_id=method.file_id, file_unique_id="u", file_path="documents/receipt.pdf")
        return True

    async def close(self) -> None:  # pragma: no cover
        pass

    async def stream_content(self, *a, **k):
        yield RECEIPT

    def sent(self) -> list[SendMessage | EditMessageText]:
        return [c for c in self.calls if isinstance(c, (SendMessage, EditMessageText))]

    def texts(self) -> list[str]:
        return [c.text for c in self.sent()]

    def last(self) -> SendMessage | EditMessageText:
        return self.sent()[-1]

    def alerts(self) -> list[str]:
        return [c.text for c in self.calls if isinstance(c, AnswerCallbackQuery) and c.text]


def buttons(method) -> list:
    return [b for row in method.reply_markup.inline_keyboard for b in row]


META = {"demo_mode": True,
        "countries": [{"code": "SA", "name_en": "Saudi Arabia", "name_ar": "السعودية",
                       "cities": [{"en": "Riyadh", "ar": "الرياض"}, {"en": "Jeddah", "ar": "جدة"}]},
                      {"code": "QA", "name_en": "Qatar", "name_ar": "قطر", "cities": []}],
        "industries": [{"key": "dental_clinics", "en": "Dental Clinics", "ar": "عيادات الأسنان"},
                       {"key": "restaurants", "en": "Restaurants", "ar": "مطاعم"}]}
CAMPAIGN = {"id": "c0ffee00-0000-0000-0000-000000000001", "name": "Dental Clinics · Riyadh", "status": "queued",
            "stage": "created", "country": "SA", "city": "Riyadh", "industry": "dental_clinics", "is_demo": False,
            "settings": {"target_count": 20}, "stats": {"target": 20, "progress": {"percent": 30}},
            "cost_discovery": 1.5, "cost_ai": 0.7, "last_error": "Google Maps unavailable (rate_limited)"}
LEAD_ROW = {"id": LEAD_ID, "name": "Bright Smile Dental", "city": "Riyadh", "latest_score": 82.0,
            "latest_priority": "high", "contact_count": 3, "has_verified_contact": True, "is_demo": False,
            "website_url": "https://brightsmile.example"}
LEAD = {
    "business": {"id": LEAD_ID, "name": "Bright Smile Dental", "industry": "dental_clinics", "city": "Riyadh",
                 "country": "SA", "website_url": "https://brightsmile.example", "crm_status": "new",
                 "latest_score": 82.0, "latest_priority": "high", "is_demo": False},
    "contacts": [
        {"type": "phone", "value": "+966 11 555 0101", "verification_status": "discovered", "is_suppressed": False,
         "source_provider": "google_maps"},
        {"type": "email", "value": "hello@brightsmile.example", "verification_status": "verified",
         "is_suppressed": False, "source_provider": "website"},
    ],
    "assessment": {"summary": "Busy clinic.", "opportunity": "No online booking; replies to WhatsApp slowly."},
    "notes": [], "suppressed": False,
}


class Backend:
    def __init__(self) -> None:
        self.linked = {LINKED, ARABIC}
        self.balance = 80
        self.providers = [{"key": "google_maps", "status": "connected"}, {"key": "osm", "status": "connected"},
                          {"key": "brave", "status": "requires_api_key"}, {"key": "demo", "status": "connected"}]
        self.created: list[dict] = []
        self.actions: list[str] = []
        self.patches: list[dict] = []
        self.notes: list[dict] = []
        self.topups: list[dict] = []
        self.links: list[dict] = []
        self.specs: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/api/v1")
        uid = request.headers.get("x-telegram-user-id")
        body = json.loads(request.content) if request.content else None
        assert request.headers.get("x-service-token") == "svc"
        if path == "/telegram/whoami":
            if uid and int(uid) in self.linked:
                return httpx.Response(200, json={"user": "a@b.c", "name": "Mona Ali", "role": "owner",
                                                 "demo_mode": False, "locale": "ar" if uid == str(ARABIC) else None})
            return httpx.Response(403, json={"error": {"message": "not linked"}})
        if path == "/telegram/status":
            status = "pending" if request.url.params["telegram_user_id"] == str(PENDING) else "unlinked"
            return httpx.Response(200, json={"status": status})
        if path == "/telegram/link":
            self.links.append(body)
            if body["code"] != "GOOD1234":
                return httpx.Response(401, json={"error": {"message": "Invalid or already used code"}})
            self.linked.add(body["telegram_user_id"])
            return httpx.Response(200, json={"status": "approved"})
        if path == "/meta":
            return httpx.Response(200, json=META)
        if path == "/providers":
            return httpx.Response(200, json=self.providers)
        if path == "/campaigns/parse-spec":
            self.specs.append(body["text"])
            return httpx.Response(200, json={"industry": "dental_clinics", "country": "SA", "city": "الرياض",
                                             "keywords": ["dentist", "طبيب أسنان"], "excluded_keywords": [],
                                             "characteristics": [], "services": [], "industry_matched": True})
        if path == "/campaigns/estimate":
            return httpx.Response(200, json={"credits_max": body["settings"]["max_companies"],
                                             "credit_balance": self.balance, "estimated_cost_usd": 1.2})
        if path == "/campaigns" and request.method == "POST":
            if self.balance <= 0:
                return httpx.Response(402, json={"error": {"code": "insufficient_credits", "message": "no"}})
            self.created.append(body)
            return httpx.Response(201, json=CAMPAIGN)
        if path == "/campaigns" and request.method == "GET":
            return httpx.Response(200, json={"items": [CAMPAIGN], "total": 1})
        if path == f"/campaigns/{CAMPAIGN['id']}":
            return httpx.Response(200, json=CAMPAIGN)
        if path.endswith("/pause"):
            self.actions.append("pause")
            return httpx.Response(200, json={**CAMPAIGN, "status": "paused"})
        if path == "/leads":
            return httpx.Response(200, json={"items": [LEAD_ROW], "total": 1})
        if path == f"/leads/{LEAD_ID}" and request.method == "GET":
            return httpx.Response(200, json=LEAD)
        if path == f"/leads/{LEAD_ID}" and request.method == "PATCH":
            self.patches.append(body)
            return httpx.Response(200, json={"message": "Lead updated"})
        if path == f"/leads/{LEAD_ID}/notes":
            self.notes.append(body)
            return httpx.Response(201, json={"id": "n1", "body": body["body"]})
        if path == "/billing/summary":
            return httpx.Response(200, json={"billing_exempt": False, "balance": self.balance, "on_trial": True,
                                             "trial_days_left": 12, "trial_expired": False, "low_balance": False,
                                             "pending_topups": len(self.topups), "awaiting_verification": False,
                                             "payment_instructions_ar": "حوّل على 0100", "payment_instructions_en":
                                             "Send to 0100"})
        if path == "/billing/packages":
            return httpx.Response(200, json=[{"id": PKG_ID, "name_ar": "أساسية", "name_en": "Basic", "credits": 500,
                                              "price": "750.00", "currency": "EGP", "featured": True}])
        if path == "/billing/topups":
            self.topups.append(body)
            return httpx.Response(201, json={"id": "t1", "status": "pending"})
        return httpx.Response(404, json={"error": {"message": "nope"}})


_DP = None


@pytest.fixture
def env():
    global _DP
    middleware._cache.clear()
    middleware.LANG_OVERRIDE.clear()
    backend = Backend()
    api = BackendClient(base_url="http://api/api/v1", service_token="svc",
                        transport=httpx.MockTransport(backend.handler))
    session = RecordingSession()
    bot = Bot(token="42:TEST", session=session)
    if _DP is None:  # aiogram routers can be attached to a single dispatcher per process
        _DP = build_dispatcher(api)
    _DP.workflow_data["auth"].api = api
    return _DP, bot, session, backend


_uid = iter(range(1, 100_000))


def _user(user_id: int) -> User:
    return User(id=user_id, is_bot=False, first_name="Tester", language_code="en")


def msg(user_id: int, text: str | None = None, **extra) -> Update:
    return Update(update_id=next(_uid), message=Message(message_id=next(_uid), date=datetime.now(), text=text,
                                                        chat=Chat(id=user_id, type="private"),
                                                        from_user=_user(user_id), **extra))


def cb(user_id: int, data: str) -> Update:
    m = Message(message_id=1, date=datetime.now(), text="x", chat=Chat(id=user_id, type="private"))
    return Update(update_id=next(_uid), callback_query=CallbackQuery(id=str(next(_uid)), from_user=_user(user_id),
                                                                     chat_instance="i", message=m, data=data))


async def feed(dp, bot, *updates):
    for update in updates:
        await dp.feed_update(bot, update)


async def run_wizard(dp, bot, user=LINKED):
    await feed(dp, bot, cb(user, "m:new"), cb(user, "w:mode:steps"), cb(user, "w:country:SA"), cb(user, "w:city:0"),
               cb(user, "w:ind:dental_clinics"), cb(user, "w:count:custom"), msg(user, "35"))


# Access & linking ------------------------------------------------------------------------------------

async def test_unlinked_user_gets_onboarding(env):
    dp, bot, session, _ = env
    await feed(dp, bot, msg(5555, "/start"))
    assert "Link your account in 3 steps" in session.texts()[-1]


async def test_pending_user_sees_pending(env):
    dp, bot, session, _ = env
    await feed(dp, bot, msg(PENDING, "/start"))
    assert "waiting" in session.texts()[-1]


async def test_link_command_links_and_opens_menu(env):
    dp, bot, session, backend = env
    await feed(dp, bot, msg(NEWBIE, "/link good1234"))
    assert backend.links[-1]["code"] == "GOOD1234"
    assert any("linked" in x for x in session.texts())
    assert any("New search" in b.text for b in buttons(session.last()))


async def test_deep_link_start_links_account(env):
    dp, bot, session, backend = env
    await feed(dp, bot, msg(NEWBIE, "/start GOOD1234"))
    assert backend.links and backend.links[-1]["telegram_user_id"] == NEWBIE
    assert "Hi Mona" in session.texts()[-1]


async def test_deep_link_with_bad_code_explains(env):
    dp, bot, session, _ = env
    await feed(dp, bot, msg(NEWBIE, "/start BADCODE1"))
    assert "did not work" in session.texts()[-1]


async def test_start_shows_main_menu(env):
    dp, bot, session, _ = env
    await feed(dp, bot, msg(LINKED, "/start"))
    sent = session.last()
    assert "Rasd" in sent.text
    labels = [b.text for b in buttons(sent)]
    for expected in ("New search", "My searches", "Best leads", "My credits", "Export", "Help"):
        assert any(expected in label for label in labels)


async def test_group_chats_are_ignored(env):
    dp, bot, session, _ = env
    update = Update(update_id=next(_uid), message=Message(message_id=1, date=datetime.now(), text="/start",
                                                          chat=Chat(id=-100, type="group"), from_user=_user(LINKED)))
    await feed(dp, bot, update)
    assert session.texts() == []


# Wizard ----------------------------------------------------------------------------------------------

async def test_step_wizard_edits_one_message_and_creates_campaign(env):
    dp, bot, session, backend = env
    await feed(dp, bot, cb(LINKED, "m:new"), cb(LINKED, "w:mode:steps"), cb(LINKED, "w:country:SA"),
               cb(LINKED, "w:city:0"), cb(LINKED, "w:ind:dental_clinics"), cb(LINKED, "w:count:custom"))
    # Button steps edit the same message instead of filling the chat.
    assert not [c for c in session.calls if isinstance(c, SendMessage)]
    await feed(dp, bot, msg(LINKED, "35"))
    summary = session.last().text
    assert "Review your search" in summary and "35 businesses" in summary and "Riyadh" in summary
    assert "Up to <b>70</b> credits" in summary and "balance: <b>80</b>" in summary
    await feed(dp, bot, cb(LINKED, "w:go"))
    body = backend.created[-1]
    assert body["country"] == "SA" and body["city"] == "Riyadh" and body["industry"] == "dental_clinics"
    assert body["sources"] == [{"provider_key": "google_maps"}, {"provider_key": "osm"}]  # connected only, no demo
    assert body["settings"]["target_count"] == 35 and body["settings"]["ai_analysis"] is True
    assert body["name"] == "Dental Clinics · Riyadh" and body["start"] is True
    assert "Search started" in session.last().text


async def test_customer_never_sees_sources_or_dollars(env):
    dp, bot, session, _ = env
    await run_wizard(dp, bot)
    await feed(dp, bot, cb(LINKED, "w:go"), cb(LINKED, f"c:view:{CAMPAIGN['id']}"))
    everything = "\n".join(session.texts()) + "\n".join(session.alerts())
    for leaked in ("Google Maps", "google_maps", "OpenStreetMap", "Brave", "$", "rate_limited"):
        assert leaked not in everything
    assert "30%" in everything


async def test_back_returns_to_previous_step(env):
    dp, bot, session, _ = env
    await feed(dp, bot, cb(LINKED, "m:new"), cb(LINKED, "w:mode:steps"), cb(LINKED, "w:country:SA"))
    assert "Which city" in session.last().text
    await feed(dp, bot, cb(LINKED, "w:back"))
    assert "Which country" in session.last().text
    await feed(dp, bot, cb(LINKED, "w:back"))
    assert "How would you like" in session.last().text


async def test_country_without_cities_skips_city_step(env):
    dp, bot, session, _ = env
    await feed(dp, bot, cb(LINKED, "m:new"), cb(LINKED, "w:mode:steps"), cb(LINKED, "w:country:QA"))
    assert "What kind of businesses" in session.last().text


async def test_plain_text_becomes_a_search(env):
    dp, bot, session, backend = env
    await feed(dp, bot, msg(LINKED, "dental clinics in Riyadh, 30 companies"))
    assert backend.specs == ["dental clinics in Riyadh, 30 companies"]
    summary = session.last().text
    assert "Review your search" in summary and "Riyadh" in summary and "30 businesses" in summary
    assert "dentist" in summary
    await feed(dp, bot, cb(LINKED, "w:go"))
    assert backend.created[-1]["city"] == "Riyadh" and backend.created[-1]["nl_query"].startswith("dental")


async def test_edit_from_summary_returns_to_summary(env):
    dp, bot, session, _ = env
    await run_wizard(dp, bot)
    await feed(dp, bot, cb(LINKED, "w:edit:count"), cb(LINKED, "w:count:100"))
    assert "100 businesses" in session.last().text
    await feed(dp, bot, cb(LINKED, "w:edit:industry"), cb(LINKED, "w:ind:restaurants"))
    assert "Review your search" in session.last().text and "Restaurants" in session.last().text


async def test_ai_toggle(env):
    dp, bot, _, backend = env
    await run_wizard(dp, bot)
    await feed(dp, bot, cb(LINKED, "w:ai"), cb(LINKED, "w:go"))
    assert backend.created[-1]["settings"]["ai_analysis"] is False


async def test_invalid_custom_count_asks_again(env):
    dp, bot, session, _ = env
    await feed(dp, bot, cb(LINKED, "m:new"), cb(LINKED, "w:mode:steps"), cb(LINKED, "w:country:SA"),
               cb(LINKED, "w:city:skip"), cb(LINKED, "w:ind:dental_clinics"), cb(LINKED, "w:count:custom"),
               msg(LINKED, "9999"))
    assert "between 1 and 500" in session.last().text


async def test_zero_balance_offers_top_up_instead_of_start(env):
    dp, bot, session, backend = env
    backend.balance = 0
    await run_wizard(dp, bot)
    summary = session.last()
    labels = [b.text for b in buttons(summary)]
    assert "no credits" in summary.text
    assert any("Top up" in x for x in labels) and not any("Start search" in x for x in labels)


async def test_stale_button_is_answered(env):
    dp, bot, session, _ = env
    await feed(dp, bot, cb(LINKED, "w:city:0"))
    assert "no longer active" in session.alerts()[-1]


# Arabic ----------------------------------------------------------------------------------------------

async def test_arabic_user_gets_arabic_everywhere(env):
    dp, bot, session, _ = env
    await feed(dp, bot, msg(ARABIC, "/start"))
    assert "رصد" in session.last().text
    await run_wizard(dp, bot, user=ARABIC)
    summary = session.last().text
    assert "راجع البحث" in summary and "الرياض" in summary and "عيادات الأسنان" in summary
    for english in ("Country", "Target", "Review", "credits", "Riyadh"):
        assert english not in summary


# Campaigns -------------------------------------------------------------------------------------------

async def test_pause_button_calls_backend(env):
    dp, bot, session, backend = env
    await feed(dp, bot, cb(LINKED, f"c:pause:{CAMPAIGN['id']}"))
    assert backend.actions == ["pause"]
    assert any("Resume" in b.text for b in buttons(session.last()))


async def test_campaign_list_opens_card(env):
    dp, bot, session, _ = env
    await feed(dp, bot, cb(LINKED, "m:mine"))
    assert "My searches" in session.last().text
    await feed(dp, bot, cb(LINKED, f"c:view:{CAMPAIGN['id']}"))
    assert "▰" in session.last().text


# Leads -----------------------------------------------------------------------------------------------

async def test_best_leads_and_lead_card_with_whatsapp(env):
    dp, bot, session, _ = env
    await feed(dp, bot, cb(LINKED, "m:top"))
    assert "Bright Smile Dental" in session.last().text and "82/100" in session.last().text
    await feed(dp, bot, cb(LINKED, f"l:v:{LEAD_ID}"))
    card = session.last()
    assert "+966 11 555 0101" in card.text and "hello@brightsmile.example" in card.text
    assert "No online booking" in card.text and "google_maps" not in card.text
    urls = [b.url for b in buttons(card) if b.url]
    assert "https://wa.me/966115550101" in urls


async def test_change_crm_status(env):
    dp, bot, session, backend = env
    await feed(dp, bot, cb(LINKED, f"l:s:{LEAD_ID}"))
    assert not any("do_not_contact" in (b.callback_data or "") for b in buttons(session.last()))
    await feed(dp, bot, cb(LINKED, f"l:st:{LEAD_ID}:contacted"))
    assert backend.patches == [{"crm_status": "contacted"}]
    assert "Status saved" in session.alerts()[-1]


async def test_add_note(env):
    dp, bot, session, backend = env
    await feed(dp, bot, cb(LINKED, f"l:n:{LEAD_ID}"), msg(LINKED, "Call on Sunday"))
    assert backend.notes == [{"body": "Call on Sunday"}]
    assert any("Note saved" in x for x in session.texts())


# Credits ---------------------------------------------------------------------------------------------

async def test_balance(env):
    dp, bot, session, _ = env
    await feed(dp, bot, msg(LINKED, "/balance"))
    assert "<b>80</b>" in session.last().text and "12 days left" in session.last().text


async def test_top_up_with_receipt(env):
    dp, bot, session, backend = env
    await feed(dp, bot, cb(LINKED, "b:pkgs"), cb(LINKED, f"b:pkg:{PKG_ID}"))
    assert "750 EGP" in session.last().text and "Send to 0100" in session.last().text
    await feed(dp, bot, cb(LINKED, "b:mth:instapay"), msg(LINKED, "REF-77"))
    assert "receipt" in session.last().text
    doc = Document(file_id="f1", file_unique_id="u1", file_name="receipt.pdf", mime_type="application/pdf",
                   file_size=len(RECEIPT))
    await feed(dp, bot, msg(LINKED, document=doc))
    assert len(backend.topups) == 1
    sent = backend.topups[0]
    assert sent["package_id"] == PKG_ID and sent["method"] == "instapay" and sent["reference"] == "REF-77"
    assert base64.b64decode(sent["receipt_base64"]) == RECEIPT
    assert "Request sent" in session.last().text


async def test_top_up_rejects_non_receipt_files(env):
    dp, bot, session, backend = env
    await feed(dp, bot, cb(LINKED, f"b:pkg:{PKG_ID}"), cb(LINKED, "b:mth:bank_transfer"), cb(LINKED, "b:skipref"))
    doc = Document(file_id="f2", file_unique_id="u2", file_name="x.zip", mime_type="application/zip", file_size=10)
    await feed(dp, bot, msg(LINKED, document=doc))
    assert not backend.topups and "a photo, an image or a PDF" in session.last().text
