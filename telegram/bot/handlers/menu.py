"""Start (with the t.me/<bot>?start=CODE deep link), linking, help, settings, language and export."""
from html import escape

from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from bot.i18n import role_label, t
from bot.keyboards.menus import back_menu_kb, export_kb, main_menu, settings_kb
from bot.middleware import LANG_OVERRIDE, _cache, _saved_lang, invalidate, user_lang
from bot.services.api import ApiError, BackendClient
from bot.ui import show

router = Router(name="menu")


async def show_menu(event: Message | CallbackQuery, lang: str, me: dict | None, edit: bool = True) -> None:
    name = (me or {}).get("name") or event.from_user.first_name or ""
    text = t("welcome", lang, name=escape(name.split()[0] if name else "")) + "\n\n" + t("welcome_tip", lang)
    if me and me.get("demo_mode"):
        text += "\n\n" + t("demo_banner", lang)
    await show(event, text, main_menu(lang, admin=bool((me or {}).get("is_superuser"))), edit=edit)


async def _link(message: Message, code: str, lang: str, api: BackendClient) -> dict | None:
    """Links the account with a one-time code; returns the account (whoami) once it is approved."""
    uid = message.from_user.id
    try:
        res = await api.link(code, uid, message.chat.id, message.from_user.username, lang)
    except ApiError as exc:
        if exc.status >= 500:
            raise
        await message.answer(t("link_failed", lang, msg=escape(exc.message)))
        return None
    invalidate(uid)
    if res.get("status") != "approved":
        await message.answer(t("pending", lang))
        return None
    await message.answer(t("linked", lang))
    return await api.whoami(uid)


@router.message(CommandStart())
async def start(message: Message, command: CommandObject, state: FSMContext, lang: str, api: BackendClient,
                me: dict | None = None) -> None:
    await state.clear()
    code = (command.args or "").strip().upper()
    if code and me is None:  # deep link: the middleware let it through without an account
        try:
            me = await api.whoami(message.from_user.id)  # already linked: ignore the (probably used) code
        except ApiError:
            me = await _link(message, code, lang, api)
            if me is None:
                return
        lang = _saved_lang(message.from_user.id, me, lang)
    await show_menu(message, lang, me, edit=False)


@router.message(Command("link"))
async def link_cmd(message: Message, command: CommandObject, lang: str, api: BackendClient) -> None:
    code = (command.args or "").strip().upper()
    if not code:
        await message.answer(t("link_usage", lang))
        return
    me = await _link(message, code, lang, api)
    if me:
        await show_menu(message, _saved_lang(message.from_user.id, me, lang), me, edit=False)


@router.message(Command("cancel"))
async def cancel_cmd(message: Message, state: FSMContext, lang: str, me: dict) -> None:
    await state.clear()
    await message.answer(t("cancelled_wizard", lang), reply_markup=main_menu(lang, admin=bool(me.get("is_superuser"))))


@router.callback_query(F.data == "m:menu")
async def menu_cb(cb: CallbackQuery, state: FSMContext, lang: str, me: dict) -> None:
    await state.clear()
    await show_menu(cb, lang, me)
    await cb.answer()


@router.message(Command("help"))
async def help_cmd(message: Message, lang: str) -> None:
    await message.answer(t("help", lang), reply_markup=back_menu_kb(lang))


@router.callback_query(F.data == "m:help")
async def help_cb(cb: CallbackQuery, lang: str) -> None:
    await show(cb, t("help", lang), back_menu_kb(lang))
    await cb.answer()


async def _toggle_lang(uid: int, language_code: str | None, api: BackendClient) -> str:
    new = "en" if user_lang(uid, language_code) == "ar" else "ar"
    LANG_OVERRIDE[uid] = new
    if uid in _cache:  # keep the cached account in step so every handler sees the new language
        _cache[uid][1]["locale"] = new
    try:
        # Persisted so campaign notifications (sent by the worker) and bot restarts use it too.
        await api.set_locale(uid, new)
    except ApiError:
        pass  # not linked yet: the in-memory choice still applies to this chat
    return new


@router.message(Command("lang"))
async def lang_cmd(message: Message, api: BackendClient) -> None:
    new = await _toggle_lang(message.from_user.id, message.from_user.language_code, api)
    await message.answer(t("lang_set", new), reply_markup=back_menu_kb(new))


def _settings_text(me: dict, lang: str) -> str:
    return t("settings", lang, user=escape(me.get("user") or "—"), role=role_label(me.get("role"), lang))


@router.callback_query(F.data == "m:settings")
async def settings_cb(cb: CallbackQuery, lang: str, me: dict) -> None:
    await show(cb, _settings_text(me, lang), settings_kb(lang))
    await cb.answer()


@router.callback_query(F.data == "m:lang")
async def lang_cb(cb: CallbackQuery, api: BackendClient, me: dict) -> None:
    new = await _toggle_lang(cb.from_user.id, cb.from_user.language_code, api)
    await show(cb, _settings_text(me, new), settings_kb(new))
    await cb.answer(t("lang_set", new))


@router.callback_query(F.data == "m:export")
async def export_cb(cb: CallbackQuery, lang: str) -> None:
    await show(cb, t("export_pick", lang), export_kb(lang))
    await cb.answer()


@router.callback_query(F.data == "m:export:qualified")
async def export_qualified(cb: CallbackQuery, lang: str, api: BackendClient) -> None:
    content = await api.leads_csv(cb.from_user.id)
    await cb.message.answer_document(BufferedInputFile(content, filename="rasd-leads.csv"),
                                     caption=t("export_caption", lang))
    await cb.answer()
