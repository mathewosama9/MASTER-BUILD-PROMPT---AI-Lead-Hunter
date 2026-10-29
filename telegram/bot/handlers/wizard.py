"""New-campaign wizard (FSM): country -> city -> industry -> sources -> count -> AI -> confirm."""
from html import escape

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.formatting import campaign_card
from bot.i18n import t
from bot.keyboards.menus import (
    SOURCE_LABELS,
    campaign_kb,
    cities_kb,
    confirm_kb,
    count_kb,
    countries_kb,
    industries_kb,
    main_menu,
    sources_kb,
    yes_no_kb,
)
from bot.services.api import ApiError, BackendClient
from bot.states.campaign import NewCampaign

router = Router(name="wizard")


async def _begin(target: Message, state: FSMContext, lang: str, api: BackendClient) -> None:
    await state.clear()
    meta = await api.meta()
    await state.update_data(sources=[], lang=lang)
    await state.set_state(NewCampaign.country)
    await target.answer(t("ask_country", lang), reply_markup=countries_kb(meta, lang))


@router.message(Command("new"))
async def new_cmd(message: Message, state: FSMContext, lang: str, api: BackendClient) -> None:
    await _begin(message, state, lang, api)


@router.callback_query(F.data == "m:new")
async def new_cb(cb: CallbackQuery, state: FSMContext, lang: str, api: BackendClient) -> None:
    await _begin(cb.message, state, lang, api)
    await cb.answer()


@router.message(Command("cancel"))
@router.callback_query(F.data == "w:cancel")
async def cancel(event: Message | CallbackQuery, state: FSMContext, lang: str) -> None:
    await state.clear()
    msg = event.message if isinstance(event, CallbackQuery) else event
    await msg.answer(t("cancelled_wizard", lang), reply_markup=main_menu(lang))
    if isinstance(event, CallbackQuery):
        await event.answer()


@router.callback_query(StateFilter(NewCampaign.country), F.data.startswith("w:country:"))
async def pick_country(cb: CallbackQuery, state: FSMContext, lang: str, api: BackendClient) -> None:
    code = cb.data.split(":")[2]
    if code == "other":
        await state.set_state(NewCampaign.custom_country)
        await cb.message.answer(t("ask_country_code", lang))
    else:
        await state.update_data(country=code)
        await state.set_state(NewCampaign.city)
        await cb.message.answer(t("ask_city", lang), reply_markup=cities_kb(await api.meta(), code, lang))
    await cb.answer()


@router.message(StateFilter(NewCampaign.custom_country), F.text)
async def custom_country(message: Message, state: FSMContext, lang: str, api: BackendClient) -> None:
    code = message.text.strip().upper()
    if len(code) != 2 or not code.isalpha():
        await message.answer(t("ask_country_code", lang))
        return
    await state.update_data(country=code)
    await state.set_state(NewCampaign.industry)
    await message.answer(t("ask_industry", lang), reply_markup=industries_kb(await api.meta(), lang))


@router.callback_query(StateFilter(NewCampaign.city), F.data.startswith("w:city:"))
async def pick_city(cb: CallbackQuery, state: FSMContext, lang: str, api: BackendClient) -> None:
    choice = cb.data.split(":")[2]
    data = await state.get_data()
    meta = await api.meta()
    if choice != "skip":
        country = next((c for c in meta["countries"] if c["code"] == data["country"]), None)
        cities = country["cities"] if country else []
        idx = int(choice)
        if 0 <= idx < len(cities):
            await state.update_data(city=cities[idx]["en"])
    await state.set_state(NewCampaign.industry)
    await cb.message.answer(t("ask_industry", lang), reply_markup=industries_kb(meta, lang))
    await cb.answer()


@router.callback_query(StateFilter(NewCampaign.industry), F.data.startswith("w:ind:"))
async def pick_industry(cb: CallbackQuery, state: FSMContext, lang: str, api: BackendClient) -> None:
    key = cb.data.split(":", 2)[2]
    if key == "custom":
        await state.set_state(NewCampaign.custom_industry)
        await cb.message.answer(t("ask_custom_industry", lang))
    else:
        await state.update_data(industry=key)
        await _ask_sources(cb.message, cb.from_user.id, state, lang, api)
    await cb.answer()


@router.message(StateFilter(NewCampaign.custom_industry), F.text)
async def custom_industry(message: Message, state: FSMContext, lang: str, api: BackendClient) -> None:
    text = message.text.strip()[:100]
    if len(text) < 2:
        await message.answer(t("ask_custom_industry", lang))
        return
    await state.update_data(industry=text)
    await _ask_sources(message, message.from_user.id, state, lang, api)


async def _ask_sources(target: Message, uid: int, state: FSMContext, lang: str, api: BackendClient) -> None:
    providers = await api.providers(uid)
    meta = await api.meta()
    await state.update_data(providers=providers, demo_mode=meta["demo_mode"])
    await state.set_state(NewCampaign.sources)
    data = await state.get_data()
    await target.answer(t("ask_sources", lang),
                        reply_markup=sources_kb(providers, set(data["sources"]), lang, meta["demo_mode"]))


@router.callback_query(StateFilter(NewCampaign.sources), F.data.startswith("w:src:"))
async def toggle_source(cb: CallbackQuery, state: FSMContext, lang: str) -> None:
    key = cb.data.split(":")[2]
    data = await state.get_data()
    selected = set(data.get("sources", []))
    providers = data.get("providers", [])
    if key == "done":
        if not selected:
            await cb.answer(t("no_sources", lang), show_alert=True)
            return
        await state.set_state(NewCampaign.count)
        await cb.message.answer(t("ask_count", lang), reply_markup=count_kb(lang))
        await cb.answer()
        return
    p = next((x for x in providers if x["key"] == key), None)
    if p is None or p["status"] != "connected":
        detail = (p or {}).get("status_detail") or "not available"
        await cb.answer(f"{SOURCE_LABELS.get(key, key)}: {detail}"[:190], show_alert=True)
        return
    # Demo and real sources cannot be mixed in one campaign.
    if key == "demo":
        selected = set() if "demo" in selected else {"demo"}
    else:
        selected.discard("demo")
        selected ^= {key}
    await state.update_data(sources=sorted(selected))
    await cb.message.edit_reply_markup(reply_markup=sources_kb(providers, selected, lang, data.get("demo_mode", False)))
    await cb.answer()


@router.callback_query(StateFilter(NewCampaign.count), F.data.startswith("w:count:"))
async def pick_count(cb: CallbackQuery, state: FSMContext, lang: str) -> None:
    v = cb.data.split(":")[2]
    if v == "custom":
        await state.set_state(NewCampaign.custom_count)
        await cb.message.answer(t("ask_custom_count", lang))
    else:
        await state.update_data(count=int(v))
        await state.set_state(NewCampaign.ai)
        await cb.message.answer(t("ask_ai", lang), reply_markup=yes_no_kb(lang, "w:ai"))
    await cb.answer()


@router.message(StateFilter(NewCampaign.custom_count), F.text)
async def custom_count(message: Message, state: FSMContext, lang: str) -> None:
    if not message.text.strip().isdigit() or not 1 <= int(message.text.strip()) <= 500:
        await message.answer(t("ask_custom_count", lang))
        return
    await state.update_data(count=int(message.text.strip()))
    await state.set_state(NewCampaign.ai)
    await message.answer(t("ask_ai", lang), reply_markup=yes_no_kb(lang, "w:ai"))


@router.callback_query(StateFilter(NewCampaign.ai), F.data.startswith("w:ai:"))
async def pick_ai(cb: CallbackQuery, state: FSMContext, lang: str) -> None:
    await state.update_data(ai=cb.data.endswith("yes"))
    await state.set_state(NewCampaign.confirm)
    data = await state.get_data()
    demo = "🧪 DEMO MODE — fictional data\n" if data["sources"] == ["demo"] else ""
    text = (
        f"{demo}{t('summary', lang)}\n\n"
        f"Country: {data['country']}\nCity: {escape(data.get('city') or '—')}\n"
        f"Industry: {escape(data['industry'])}\nSources: {', '.join(data['sources'])}\n"
        f"Target: {data['count']}\nAI analysis: {'Yes' if data['ai'] else 'No'}"
    )
    await cb.message.answer(text, reply_markup=confirm_kb(lang))
    await cb.answer()


@router.callback_query(StateFilter(NewCampaign.confirm), F.data == "w:edit")
async def edit(cb: CallbackQuery, state: FSMContext, lang: str, api: BackendClient) -> None:
    await _begin(cb.message, state, lang, api)
    await cb.answer()


@router.callback_query(StateFilter(NewCampaign.confirm), F.data == "w:go")
async def go(cb: CallbackQuery, state: FSMContext, lang: str, api: BackendClient) -> None:
    data = await state.get_data()
    count = int(data["count"])
    city = data.get("city")
    body = {
        "name": f"{data['industry'].replace('_', ' ').title()} · {city or data['country']} (Telegram)",
        "country": data["country"], "city": city, "industry": data["industry"], "language": lang,
        "sources": [{"provider_key": s} for s in data["sources"]],
        "settings": {"target_count": count, "max_companies": min(count * 2, 1000), "ai_analysis": data["ai"]},
        "start": True,
    }
    try:
        c = await api.create_campaign(cb.from_user.id, body)
    except ApiError as exc:
        await cb.answer(exc.message[:190], show_alert=True)
        return
    await state.clear()
    await cb.message.answer(f"{t('started', lang)}\n\n{campaign_card(c)}",
                            reply_markup=campaign_kb(c["id"], c["status"], lang))
    await cb.answer()
