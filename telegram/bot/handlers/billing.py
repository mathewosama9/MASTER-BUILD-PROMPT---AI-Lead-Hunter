"""Credits: balance and trial; packages are bought with PayPal on the website."""
from html import escape

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.formatting import balance_card
from bot.i18n import t
from bot.keyboards.menus import balance_kb, money_text, packages_kb, pay_kb, web_url
from bot.services.api import BackendClient
from bot.ui import show

router = Router(name="billing")


async def show_balance(event: Message | CallbackQuery, lang: str, api: BackendClient, edit: bool = True) -> None:
    s = await api.billing_summary(event.from_user.id)
    await show(event, balance_card(s, lang), balance_kb(lang, can_topup=not s.get("billing_exempt")), edit=edit)


@router.message(Command("balance"))
async def balance_cmd(message: Message, state: FSMContext, lang: str, api: BackendClient, me: dict) -> None:
    await state.set_state(None)
    await show_balance(message, lang, api)


@router.callback_query(F.data.in_({"b:bal", "b:cancel"}))
async def balance_cb(cb: CallbackQuery, state: FSMContext, lang: str, api: BackendClient) -> None:
    await state.set_state(None)
    await show_balance(cb, lang, api)
    await cb.answer()


@router.callback_query(F.data == "b:pkgs")
async def packages_cb(cb: CallbackQuery, state: FSMContext, lang: str, api: BackendClient) -> None:
    await state.clear()  # also leaves the search wizard when "Top up" is pressed on its summary
    packages = await api.packages(cb.from_user.id)
    if not packages:
        await cb.answer(t("no_packages", lang), show_alert=True)
        return
    await show(cb, t("pick_package", lang), packages_kb(packages, lang))
    await cb.answer()


@router.callback_query(F.data.startswith("b:pkg:"))
async def package_cb(cb: CallbackQuery, state: FSMContext, lang: str, api: BackendClient) -> None:
    """Packages are paid with PayPal on the website; the bot links straight to the chosen package."""
    package_id = cb.data.split(":", 2)[2]
    pkg = next((p for p in await api.packages(cb.from_user.id) if p["id"] == package_id), None)
    if pkg is None:
        await cb.answer(t("no_packages", lang), show_alert=True)
        return
    name = pkg["name_ar"] if lang == "ar" else pkg["name_en"]
    url = web_url(f"/app/billing?pkg={package_id}")
    text = t("pay_on_web", lang, name=escape(name), credits=pkg["credits"],
             price=money_text(pkg["price"], pkg["currency"]))
    await show(cb, text if url else text + "\n\n" + t("pay_on_web_no_link", lang), pay_kb(lang, url))
    await cb.answer()
