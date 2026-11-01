"""New-search wizard. One message is edited from step to step (with Back), or the user types a request in
their own words and lands on the summary straight away.

Steps: mode -> country -> city -> industry -> count -> summary. Discovery sources are chosen automatically
(customers never see source names), and the summary shows the credit estimate before anything starts.
"""
import re
from contextlib import suppress

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from bot.formatting import campaign_card, country_name, industry_name, summary_card
from bot.i18n import t
from bot.keyboards.menus import (
    campaign_kb,
    cities_kb,
    count_kb,
    countries_kb,
    industries_kb,
    main_menu,
    mode_kb,
    summary_kb,
    text_input_kb,
)
from bot.services.api import ApiError, BackendClient
from bot.states.campaign import NewCampaign
from bot.ui import credit_message, show

router = Router(name="wizard")

# Same order as the dashboard's first search (backend api/v1/profile.py FIRST_SEARCH_SOURCES).
AUTO_SOURCES = ("google_maps", "osm", "directories", "social_discovery", "brave")
# Text-input steps are not kept in the Back history: Back returns to the buttons they came from.
TEXT_STEPS = {"free_text", "custom_country", "custom_city", "custom_industry", "custom_count"}
STEP_NO = {"country": 1, "city": 2, "industry": 3, "count": 4}
TEXT_INPUT = F.text & ~F.text.startswith("/")
ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")


def pick_sources(providers: list[dict], demo_mode: bool) -> list[str]:
    connected = {p["key"] for p in providers if p.get("status") == "connected"}
    real = [k for k in AUTO_SOURCES if k in connected]
    if real:
        return real
    return ["demo"] if demo_mode and "demo" in connected else []


def campaign_body(data: dict, lang: str, meta: dict, start: bool) -> dict:
    industry = data.get("industry_label") or industry_name(meta, data["industry"], lang)
    place = data.get("city_label") or data.get("city") or country_name(meta, data["country"], lang)
    count = int(data["count"])
    body = {
        "name": f"{industry} · {place}"[:200],
        "country": data["country"],
        "city": data.get("city"),
        "industry": data["industry"],
        "language": lang,
        "keywords": [k[:120] for k in data.get("keywords", [])][:30],
        "excluded_keywords": [k[:120] for k in data.get("excluded_keywords", [])][:30],
        "characteristics": [k[:200] for k in data.get("characteristics", [])][:20],
        "services": data.get("services", [])[:10],
        "sources": [{"provider_key": s} for s in data["sources"]],
        "settings": {"target_count": count, "max_companies": min(count * 2, 1000),
                     "ai_analysis": data.get("ai", True)},
        "start": start,
    }
    if data.get("nl_query"):
        body["nl_query"] = data["nl_query"][:2000]
    return body


def _complete(data: dict) -> bool:
    return bool(data.get("country") and data.get("industry") and data.get("count"))


# Rendering -------------------------------------------------------------------------------------------

async def _render(event: Message | CallbackQuery, state: FSMContext, text: str, kb: InlineKeyboardMarkup) -> None:
    """Button presses edit the wizard message; typed answers replace it, so the step stays at the bottom."""
    if isinstance(event, CallbackQuery):
        msg = await show(event, text, kb)
    else:
        old = (await state.get_data()).get("wizard_msg_id")
        if old:
            with suppress(TelegramBadRequest):
                await event.bot.delete_message(event.chat.id, old)
        msg = await event.answer(text, reply_markup=kb)
    await state.update_data(wizard_msg_id=msg.message_id)


def _numbered(step: str, text: str, lang: str) -> str:
    n = STEP_NO.get(step)
    return f"<i>{t('step', lang, n=n)}</i>\n{text}" if n else text


async def _view(step: str, data: dict, lang: str, api: BackendClient, uid: int,
                state: FSMContext) -> tuple[str, InlineKeyboardMarkup]:
    meta = await api.meta()
    if step == "mode":
        return t("ask_mode", lang), mode_kb(lang)
    if step == "free_text":
        return t("ask_free_text", lang), text_input_kb(lang)
    if step == "country":
        return _numbered(step, t("ask_country", lang), lang), countries_kb(meta, lang)
    if step == "custom_country":
        return t("ask_country_code", lang), text_input_kb(lang)
    if step == "city":
        name = country_name(meta, data["country"], lang)
        return (_numbered(step, t("ask_city", lang, country=name), lang),
                cities_kb(meta, data["country"], lang, data.get("city_page", 0)))
    if step == "custom_city":
        return t("ask_custom_city", lang), text_input_kb(lang)
    if step == "industry":
        return _numbered(step, t("ask_industry", lang), lang), industries_kb(meta, lang, data.get("ind_page", 0))
    if step == "custom_industry":
        return t("ask_custom_industry", lang), text_input_kb(lang)
    if step == "count":
        return _numbered(step, t("ask_count", lang), lang), count_kb(lang)
    if step == "custom_count":
        return t("ask_custom_count", lang), text_input_kb(lang)
    # summary
    sources = pick_sources(await api.providers(uid), meta["demo_mode"])
    await state.update_data(sources=sources)
    data = {**data, "sources": sources}
    estimate = None
    if sources:
        try:
            estimate = await api.estimate(uid, campaign_body(data, lang, meta, start=False))
        except ApiError:
            estimate = None  # the summary still works; the backend re-checks credits on start
    balance = (estimate or {}).get("credit_balance")
    need_topup = balance is not None and balance <= 0 and sources != ["demo"]
    kb = summary_kb(lang, data.get("ai", True), can_start=bool(sources) and not need_topup, need_topup=need_topup)
    return summary_card(data, estimate, lang, meta), kb


async def goto(event: Message | CallbackQuery, state: FSMContext, step: str, lang: str, api: BackendClient,
               push: bool = True) -> None:
    data = await state.get_data()
    current = data.get("step")
    if push and current and current != step and current not in TEXT_STEPS:
        await state.update_data(history=[*data.get("history", []), current][-15:])
    await state.update_data(step=step)
    await state.set_state(getattr(NewCampaign, step))
    text, kb = await _view(step, await state.get_data(), lang, api, event.from_user.id, state)
    await _render(event, state, text, kb)


async def advance(event: Message | CallbackQuery, state: FSMContext, natural_next: str, lang: str,
                  api: BackendClient) -> None:
    """Next step, or straight back to the summary when the user is only changing one answer."""
    data = await state.get_data()
    if data.get("editing") and _complete(data):
        await state.update_data(editing=False)
        await goto(event, state, "summary", lang, api)
    else:
        await goto(event, state, natural_next, lang, api)


async def _has_cities(api: BackendClient, code: str) -> bool:
    meta = await api.meta()
    c = next((x for x in meta["countries"] if x["code"] == code), None)
    return bool(c and c.get("cities"))


async def _after_country(event: Message | CallbackQuery, state: FSMContext, code: str, lang: str,
                         api: BackendClient) -> None:
    await state.update_data(country=code, city=None, city_label=None, city_page=0)
    if await _has_cities(api, code):
        await goto(event, state, "city", lang, api)
    else:
        await advance(event, state, "industry", lang, api)


# Entry points ----------------------------------------------------------------------------------------

async def begin(event: Message | CallbackQuery, state: FSMContext, lang: str, api: BackendClient,
                step: str = "mode") -> None:
    await state.clear()
    await state.update_data(history=[], ai=True)
    await goto(event, state, step, lang, api, push=False)


@router.message(Command("new"))
async def new_cmd(message: Message, state: FSMContext, lang: str, api: BackendClient, me: dict) -> None:
    await begin(message, state, lang, api)


@router.callback_query(F.data == "m:new")
async def new_cb(cb: CallbackQuery, state: FSMContext, lang: str, api: BackendClient, me: dict) -> None:
    await begin(cb, state, lang, api)
    await cb.answer()


@router.callback_query(F.data == "w:cancel")
async def cancel(cb: CallbackQuery, state: FSMContext, lang: str) -> None:
    await state.clear()
    await show(cb, t("cancelled_wizard", lang), main_menu(lang))
    await cb.answer()


@router.callback_query(StateFilter(NewCampaign), F.data == "w:back")
async def back(cb: CallbackQuery, state: FSMContext, lang: str, api: BackendClient) -> None:
    history = list((await state.get_data()).get("history", []))
    previous = history.pop() if history else "mode"
    await state.update_data(history=history, editing=False)
    await goto(cb, state, previous, lang, api, push=False)
    await cb.answer()


@router.callback_query(StateFilter(NewCampaign.mode), F.data.startswith("w:mode:"))
async def pick_mode(cb: CallbackQuery, state: FSMContext, lang: str, api: BackendClient) -> None:
    await goto(cb, state, "free_text" if cb.data.endswith(":text") else "country", lang, api)
    await cb.answer()


# Free text ("dental clinics in Riyadh") --------------------------------------------------------------

def _count_from_text(text: str) -> int | None:
    for match in re.findall(r"\d{1,4}", text.translate(ARABIC_DIGITS)):
        if 1 <= int(match) <= 500:
            return int(match)
    return None


async def from_text(message: Message, state: FSMContext, lang: str, api: BackendClient) -> None:
    text = message.text.strip()
    if len(text) < 3:
        await goto(message, state, "free_text", lang, api, push=False)
        return
    await state.set_state(NewCampaign.free_text)
    wait = await message.answer(t("parsing", lang))
    old = (await state.get_data()).get("wizard_msg_id")
    if old:
        with suppress(TelegramBadRequest):
            await message.bot.delete_message(message.chat.id, old)
    await state.update_data(wizard_msg_id=wait.message_id)
    try:
        spec = await api.parse_spec(message.from_user.id, text)
    except ApiError as exc:
        if exc.status >= 500 or exc.status == 403:
            raise
        spec = {}
    meta = await api.meta()
    codes = {c["code"] for c in meta["countries"]}
    country = (spec.get("country") or "").upper()
    if country not in codes and not (len(country) == 2 and country.isalpha()):
        country = None
    city = spec.get("city") or None
    city_label = city
    match = next((c for c in meta["countries"] if c["code"] == country), None)
    for c in (match or {}).get("cities", []):
        if city and city.casefold() in (c["en"].casefold(), c["ar"]):
            city, city_label = c["en"], (c["ar"] if lang == "ar" else c["en"])
    industry = spec.get("industry") if spec.get("industry_matched", True) else None
    known = {i["key"] for i in meta["industries"]}
    await state.update_data(
        country=country, city=city if country else None, city_label=city_label if country else None,
        industry=industry, industry_label=None if industry in known else industry,
        keywords=spec.get("keywords") or [], excluded_keywords=spec.get("excluded_keywords") or [],
        characteristics=spec.get("characteristics") or [], services=spec.get("services") or [],
        count=_count_from_text(text) or 20, nl_query=text, editing=True,
    )
    if not country:
        await goto(message, state, "country", lang, api)
    elif not industry:
        await goto(message, state, "industry", lang, api)
    else:
        await state.update_data(editing=False)
        await goto(message, state, "summary", lang, api)


@router.message(StateFilter(NewCampaign.free_text), TEXT_INPUT)
async def free_text(message: Message, state: FSMContext, lang: str, api: BackendClient) -> None:
    await from_text(message, state, lang, api)


# Country / city --------------------------------------------------------------------------------------

@router.callback_query(StateFilter(NewCampaign.country), F.data.startswith("w:country:"))
async def pick_country(cb: CallbackQuery, state: FSMContext, lang: str, api: BackendClient) -> None:
    code = cb.data.split(":")[2]
    if code == "other":
        await goto(cb, state, "custom_country", lang, api)
    else:
        await _after_country(cb, state, code, lang, api)
    await cb.answer()


@router.message(StateFilter(NewCampaign.custom_country), TEXT_INPUT)
async def custom_country(message: Message, state: FSMContext, lang: str, api: BackendClient) -> None:
    code = message.text.strip().upper()
    if len(code) != 2 or not code.isalpha():
        await goto(message, state, "custom_country", lang, api, push=False)
        return
    await _after_country(message, state, code, lang, api)


@router.callback_query(StateFilter(NewCampaign.city), F.data.startswith("w:cpage:"))
async def city_page(cb: CallbackQuery, state: FSMContext, lang: str, api: BackendClient) -> None:
    await state.update_data(city_page=int(cb.data.split(":")[2]))
    await goto(cb, state, "city", lang, api, push=False)
    await cb.answer()


@router.callback_query(StateFilter(NewCampaign.city), F.data.startswith("w:city:"))
async def pick_city(cb: CallbackQuery, state: FSMContext, lang: str, api: BackendClient) -> None:
    choice = cb.data.split(":")[2]
    if choice == "other":
        await goto(cb, state, "custom_city", lang, api)
        await cb.answer()
        return
    city = label = None
    if choice != "skip":
        data = await state.get_data()
        meta = await api.meta()
        country = next((c for c in meta["countries"] if c["code"] == data["country"]), None)
        cities = country["cities"] if country else []
        idx = int(choice)
        if 0 <= idx < len(cities):
            city, label = cities[idx]["en"], (cities[idx]["ar"] if lang == "ar" else cities[idx]["en"])
    await state.update_data(city=city, city_label=label)
    await advance(cb, state, "industry", lang, api)
    await cb.answer()


@router.message(StateFilter(NewCampaign.custom_city), TEXT_INPUT)
async def custom_city(message: Message, state: FSMContext, lang: str, api: BackendClient) -> None:
    city = message.text.strip()[:120]
    if len(city) < 2:
        await goto(message, state, "custom_city", lang, api, push=False)
        return
    await state.update_data(city=city, city_label=city)
    await advance(message, state, "industry", lang, api)


# Industry / count ------------------------------------------------------------------------------------

@router.callback_query(StateFilter(NewCampaign.industry), F.data.startswith("w:ipage:"))
async def industry_page(cb: CallbackQuery, state: FSMContext, lang: str, api: BackendClient) -> None:
    await state.update_data(ind_page=int(cb.data.split(":")[2]))
    await goto(cb, state, "industry", lang, api, push=False)
    await cb.answer()


@router.callback_query(StateFilter(NewCampaign.industry), F.data.startswith("w:ind:"))
async def pick_industry(cb: CallbackQuery, state: FSMContext, lang: str, api: BackendClient) -> None:
    key = cb.data.split(":", 2)[2]
    if key == "custom":
        await goto(cb, state, "custom_industry", lang, api)
    else:
        await state.update_data(industry=key, industry_label=None)
        await advance(cb, state, "count", lang, api)
    await cb.answer()


@router.message(StateFilter(NewCampaign.custom_industry), TEXT_INPUT)
async def custom_industry(message: Message, state: FSMContext, lang: str, api: BackendClient) -> None:
    text = message.text.strip()[:100]
    if len(text) < 2:
        await goto(message, state, "custom_industry", lang, api, push=False)
        return
    await state.update_data(industry=text, industry_label=text)
    await advance(message, state, "count", lang, api)


@router.callback_query(StateFilter(NewCampaign.count), F.data.startswith("w:count:"))
async def pick_count(cb: CallbackQuery, state: FSMContext, lang: str, api: BackendClient) -> None:
    v = cb.data.split(":")[2]
    if v == "custom":
        await goto(cb, state, "custom_count", lang, api)
    else:
        await state.update_data(count=int(v), editing=False)
        await goto(cb, state, "summary", lang, api)
    await cb.answer()


@router.message(StateFilter(NewCampaign.custom_count), TEXT_INPUT)
async def custom_count(message: Message, state: FSMContext, lang: str, api: BackendClient) -> None:
    raw = message.text.strip().translate(ARABIC_DIGITS)
    if not raw.isdigit() or not 1 <= int(raw) <= 500:
        await goto(message, state, "custom_count", lang, api, push=False)
        return
    await state.update_data(count=int(raw), editing=False)
    await goto(message, state, "summary", lang, api)


# Summary ---------------------------------------------------------------------------------------------

@router.callback_query(StateFilter(NewCampaign.summary), F.data == "w:ai")
async def toggle_ai(cb: CallbackQuery, state: FSMContext, lang: str, api: BackendClient) -> None:
    await state.update_data(ai=not (await state.get_data()).get("ai", True))
    await goto(cb, state, "summary", lang, api, push=False)
    await cb.answer()


@router.callback_query(StateFilter(NewCampaign.summary), F.data.startswith("w:edit:"))
async def edit_field(cb: CallbackQuery, state: FSMContext, lang: str, api: BackendClient) -> None:
    field = cb.data.split(":")[2]
    await state.update_data(editing=True)
    await goto(cb, state, field if field in ("country", "industry", "count") else "summary", lang, api)
    await cb.answer()


@router.callback_query(StateFilter(NewCampaign.summary), F.data == "w:go")
async def go(cb: CallbackQuery, state: FSMContext, lang: str, api: BackendClient) -> None:
    data = await state.get_data()
    meta = await api.meta()
    if not data.get("sources"):
        await cb.answer(t("no_sources", lang), show_alert=True)
        return
    try:
        c = await api.create_campaign(cb.from_user.id, campaign_body(data, lang, meta, start=True))
    except ApiError as exc:
        text = credit_message(exc.code, lang)
        if text is None:
            raise
        await cb.answer(text[:190], show_alert=True)
        await goto(cb, state, "summary", lang, api, push=False)  # now shows the top-up button
        return
    await state.clear()
    await show(cb, f"{t('started', lang)}\n\n{campaign_card(c, lang, meta)}", campaign_kb(c["id"], c["status"], lang))
    await cb.answer()


# Typing instead of pressing a button -----------------------------------------------------------------

@router.message(StateFilter(NewCampaign), TEXT_INPUT)
async def typed_during_wizard(message: Message, state: FSMContext, lang: str, api: BackendClient) -> None:
    """Text on a button step is read as a new request in the user's own words."""
    await from_text(message, state, lang, api)


@router.message(StateFilter(None), TEXT_INPUT)
async def plain_text_search(message: Message, state: FSMContext, lang: str, api: BackendClient, me: dict) -> None:
    """Any plain message outside a flow starts a search from it: the fastest way to use the bot."""
    await state.clear()
    await state.update_data(history=[], ai=True)
    await from_text(message, state, lang, api)
