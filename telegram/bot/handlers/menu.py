from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from bot.formatting import campaign_card, leads_list
from bot.i18n import t
from bot.keyboards.menus import campaign_kb, main_menu
from bot.middleware import LANG_OVERRIDE, invalidate, user_lang
from bot.services.api import ApiError, BackendClient

router = Router(name="menu")


async def show_menu(target: Message, lang: str, me: dict | None) -> None:
    text = t("welcome", lang)
    if me and me.get("demo_mode"):
        text += "\n\n" + t("demo_banner", lang)
    await target.answer(text, reply_markup=main_menu(lang))


@router.message(CommandStart())
async def start(message: Message, lang: str, me: dict) -> None:
    await show_menu(message, lang, me)


@router.message(Command("help"))
async def help_cmd(message: Message, lang: str) -> None:
    await message.answer(t("help", lang))


@router.message(Command("lang"))
async def lang_cmd(message: Message, api: BackendClient) -> None:
    current = user_lang(message.from_user.id, message.from_user.language_code)
    LANG_OVERRIDE[message.from_user.id] = "en" if current == "ar" else "ar"
    new = LANG_OVERRIDE[message.from_user.id]
    try:
        # Persisted so campaign notifications (sent by the worker) and bot restarts use it too.
        await api.set_locale(message.from_user.id, new)
    except ApiError:
        pass  # not linked yet: the in-memory choice still applies to this chat
    await message.answer("Language: English" if new == "en" else "اللغة: العربية")


@router.message(Command("link"))
async def link_cmd(message: Message, command: CommandObject, lang: str, api: BackendClient) -> None:
    code = (command.args or "").strip().upper()
    if not code:
        await message.answer(t("link_usage", lang))
        return
    try:
        res = await api.link(code, message.from_user.id, message.chat.id, message.from_user.username, lang)
    except ApiError as exc:
        await message.answer(t("error", lang, msg=exc.message))
        return
    invalidate(message.from_user.id)
    await message.answer(t("linked", lang) if res["status"] == "approved" else t("pending", lang))


@router.callback_query(F.data == "m:menu")
async def menu_cb(cb: CallbackQuery, lang: str, me: dict) -> None:
    await show_menu(cb.message, lang, me)
    await cb.answer()


@router.callback_query(F.data == "m:help")
async def help_cb(cb: CallbackQuery, lang: str) -> None:
    await cb.message.answer(t("help", lang))
    await cb.answer()


@router.callback_query(F.data == "m:settings")
async def settings_cb(cb: CallbackQuery, lang: str, me: dict) -> None:
    await cb.message.answer(
        f"⚙️ Account: {me['user']}\nRole: {me['role']}\nLanguage: {lang} (/lang to switch)\n"
        f"Demo mode: {'on' if me.get('demo_mode') else 'off'}\n\n"
        "Integrations and API keys are managed by administrators in the web dashboard only.")
    await cb.answer()


@router.message(Command("campaigns"))
async def campaigns_cmd(message: Message, lang: str, api: BackendClient) -> None:
    await _list_campaigns(message, message.from_user.id, lang, api)


@router.callback_query(F.data == "m:mine")
async def mine_cb(cb: CallbackQuery, lang: str, api: BackendClient) -> None:
    await _list_campaigns(cb.message, cb.from_user.id, lang, api)
    await cb.answer()


async def _list_campaigns(target: Message, uid: int, lang: str, api: BackendClient) -> None:
    try:
        data = await api.campaigns(uid)
    except ApiError as exc:
        await target.answer(t("error", lang, msg=exc.message))
        return
    if not data["items"]:
        await target.answer(t("no_campaigns", lang), reply_markup=main_menu(lang))
        return
    for c in data["items"][:5]:
        await target.answer(campaign_card(c), reply_markup=campaign_kb(c["id"], c["status"], lang))


@router.message(Command("top"))
async def top_cmd(message: Message, lang: str, api: BackendClient) -> None:
    await _top(message, message.from_user.id, lang, api, None)


@router.callback_query(F.data.in_({"m:top", "m:results"}))
async def top_cb(cb: CallbackQuery, lang: str, api: BackendClient) -> None:
    qualified = cb.data == "m:top"
    await _top(cb.message, cb.from_user.id, lang, api, None, qualified_only=qualified)
    await cb.answer()


async def _top(target: Message, uid: int, lang: str, api: BackendClient, campaign_id: str | None,
               qualified_only: bool = True) -> None:
    try:
        data = await api.leads(uid, campaign_id=campaign_id, page_size=10, sort="score",
                               qualified_only=qualified_only or None)
    except ApiError as exc:
        await target.answer(t("error", lang, msg=exc.message))
        return
    if not data["items"]:
        await target.answer(t("no_leads", lang))
        return
    title = "🏆 Top leads" if qualified_only else "🔎 Latest results"
    await target.answer(leads_list(data["items"], f"{title} ({data['total']} total)"))


@router.callback_query(F.data == "m:stats")
async def stats_cb(cb: CallbackQuery, lang: str, api: BackendClient) -> None:
    try:
        s = (await api.stats(cb.from_user.id))["totals"]
    except ApiError as exc:
        await cb.answer(exc.message[:190], show_alert=True)
        return
    avg = f"{s['average_score']}" if s.get("average_score") is not None else "—"
    await cb.message.answer(
        "📊 <b>Workspace statistics</b>\n"
        f"Businesses: {s['businesses']}\nQualified leads: {s['qualified_leads']}\n"
        f"With contact info: {s['with_contact']} (verified: {s['with_verified_contact']})\n"
        f"Average score: {avg}\nActive campaigns: {s['active_campaigns']} · Completed: {s['completed_campaigns']}"
        f" · Failed: {s['failed_campaigns']}\nToday / week / month: {s['today']} / {s['week']} / {s['month']}\n"
        f"Costs: discovery ${s['discovery_cost_usd']:.2f} · AI ${s['ai_cost_usd']:.2f}")
    await cb.answer()


@router.callback_query(F.data == "m:export")
async def export_cb(cb: CallbackQuery, lang: str, api: BackendClient) -> None:
    try:
        content = await api.leads_csv(cb.from_user.id)
    except ApiError as exc:
        await cb.answer(exc.message[:190], show_alert=True)
        return
    await cb.message.answer_document(BufferedInputFile(content, filename="qualified-leads.csv"),
                                     caption="📤 Qualified leads (UTF-8 CSV)")
    await cb.answer()


@router.callback_query(F.data.startswith("c:"))
async def campaign_action(cb: CallbackQuery, lang: str, api: BackendClient) -> None:
    _, action, cid = cb.data.split(":", 2)
    uid = cb.from_user.id
    try:
        if action in ("pause", "cancel", "resume", "retry"):
            c = await api.action(uid, cid, action)
            await cb.message.edit_text(campaign_card(c), reply_markup=campaign_kb(cid, c["status"], lang))
            await cb.answer(f"{action.title()} ✔")
            return
        if action == "prog":
            c = await api.campaign(uid, cid)
            try:
                await cb.message.edit_text(campaign_card(c), reply_markup=campaign_kb(cid, c["status"], lang))
            except TelegramBadRequest:
                pass  # "message is not modified" when nothing changed
            await cb.answer("Updated")
            return
        if action == "res":
            await _top(cb.message, uid, lang, api, cid, qualified_only=False)
        elif action == "top":
            await _top(cb.message, uid, lang, api, cid, qualified_only=True)
        elif action == "csv":
            content = await api.campaign_csv(uid, cid)
            await cb.message.answer_document(BufferedInputFile(content, filename=f"campaign-{cid[:8]}.csv"))
        await cb.answer()
    except ApiError as exc:
        await cb.answer(exc.message[:190], show_alert=True)
