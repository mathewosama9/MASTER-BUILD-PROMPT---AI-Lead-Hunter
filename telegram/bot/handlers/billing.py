"""Credits: balance and trial, and a manual top-up (package -> payment method -> reference -> receipt)."""
import base64
from html import escape

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.formatting import balance_card
from bot.i18n import METHODS, t
from bot.keyboards.menus import balance_kb, cancel_topup_kb, methods_kb, packages_kb, price_text, reference_kb
from bot.services.api import ApiError, BackendClient
from bot.states.campaign import TopUp
from bot.ui import show

router = Router(name="billing")
MAX_RECEIPT_BYTES = 5 * 1024 * 1024
TEXT_INPUT = F.text & ~F.text.startswith("/")


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
    package_id = cb.data.split(":", 2)[2]
    pkg = next((p for p in await api.packages(cb.from_user.id) if p["id"] == package_id), None)
    if pkg is None:
        await cb.answer(t("no_packages", lang), show_alert=True)
        return
    name = pkg["name_ar"] if lang == "ar" else pkg["name_en"]
    await state.set_state(TopUp.method)
    await state.update_data(topup={"package_id": package_id})
    text = t("pick_method", lang, name=escape(name), credits=pkg["credits"], price=price_text(pkg["price"]),
             currency=escape(pkg["currency"]))
    summary = await api.billing_summary(cb.from_user.id)
    instructions = summary.get("payment_instructions_ar" if lang == "ar" else "payment_instructions_en")
    if instructions:
        text += "\n\n" + t("pay_instructions", lang, text=escape(instructions))
    await show(cb, text, methods_kb(lang))
    await cb.answer()


@router.callback_query(StateFilter(TopUp.method), F.data.startswith("b:mth:"))
async def method_cb(cb: CallbackQuery, state: FSMContext, lang: str) -> None:
    method = cb.data.split(":", 2)[2]
    if method not in METHODS:
        await cb.answer(t("expired_button", lang), show_alert=True)
        return
    topup = (await state.get_data()).get("topup", {})
    await state.update_data(topup={**topup, "method": method})
    await state.set_state(TopUp.reference)
    await show(cb, t("ask_reference", lang), reference_kb(lang))
    await cb.answer()


@router.callback_query(StateFilter(TopUp.reference), F.data == "b:skipref")
async def skip_reference(cb: CallbackQuery, state: FSMContext, lang: str) -> None:
    await state.set_state(TopUp.receipt)
    await show(cb, t("ask_receipt", lang), cancel_topup_kb(lang))
    await cb.answer()


@router.message(StateFilter(TopUp.reference), TEXT_INPUT)
async def reference_text(message: Message, state: FSMContext, lang: str) -> None:
    topup = (await state.get_data()).get("topup", {})
    await state.update_data(topup={**topup, "reference": message.text.strip()[:200]})
    await state.set_state(TopUp.receipt)
    await message.answer(t("ask_receipt", lang), reply_markup=cancel_topup_kb(lang))


@router.message(StateFilter(TopUp.receipt), F.photo | F.document)
async def receipt(message: Message, state: FSMContext, lang: str, api: BackendClient) -> None:
    if message.photo:
        file, filename = message.photo[-1], "receipt.jpg"
    else:
        file, filename = message.document, message.document.file_name or "receipt"
        mime = message.document.mime_type or ""
        if not (mime.startswith("image/") or mime == "application/pdf"):
            await message.answer(t("receipt_invalid", lang), reply_markup=cancel_topup_kb(lang))
            return
    if (file.file_size or 0) > MAX_RECEIPT_BYTES:
        await message.answer(t("receipt_invalid", lang), reply_markup=cancel_topup_kb(lang))
        return
    topup = (await state.get_data()).get("topup", {})
    if not topup.get("package_id") or not topup.get("method"):
        await state.clear()
        await show_balance(message, lang, api, edit=False)
        return
    wait = await message.answer(t("uploading", lang))
    content = (await message.bot.download(file.file_id)).read()
    body = {"package_id": topup["package_id"], "method": topup["method"], "reference": topup.get("reference"),
            "receipt_filename": filename[:200], "receipt_base64": base64.b64encode(content).decode()}
    try:
        await api.create_topup(message.from_user.id, body)
    except ApiError as exc:
        if exc.status == 403:
            await state.clear()
            await wait.edit_text(t("topup_admin_only", lang))
            return
        if exc.status >= 500:
            raise
        await wait.edit_text(t("error", lang, msg=escape(exc.message)), reply_markup=cancel_topup_kb(lang))
        return  # stays on the receipt step so another file can be sent
    await state.clear()
    s = await api.billing_summary(message.from_user.id)
    await wait.edit_text(t("topup_sent", lang) + "\n\n" + balance_card(s, lang),
                         reply_markup=balance_kb(lang, can_topup=False))


@router.message(StateFilter(TopUp.receipt))
async def receipt_missing(message: Message, lang: str) -> None:
    await message.answer(t("receipt_invalid", lang), reply_markup=cancel_topup_kb(lang))
