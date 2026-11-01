"""Leads: paged best/all lists, the full lead card (contacts, why it fits, WhatsApp), CRM status and notes."""
import math
from html import escape

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.formatting import lead_card, leads_page, whatsapp_number
from bot.i18n import t
from bot.keyboards.menus import BOT_CRM_STATUSES, back_menu_kb, crm_kb, lead_kb, leads_kb, note_kb
from bot.services.api import BackendClient
from bot.states.campaign import NoteInput
from bot.ui import show

router = Router(name="leads")
PAGE_SIZE = 8
TEXT_INPUT = F.text & ~F.text.startswith("/")


async def show_leads(event: Message | CallbackQuery, lang: str, api: BackendClient, page: int = 1,
                     qualified: bool = True, cid: str | None = None, edit: bool = True,
                     state: FSMContext | None = None) -> None:
    data = await api.leads(event.from_user.id, page=page, page_size=PAGE_SIZE, sort="score", campaign_id=cid,
                           qualified_only=True if qualified else None)
    if state is not None:  # remembered for the card's "Back to list"
        await state.update_data(leads_ctx={"page": page, "q": qualified, "cid": cid})
    if not data["items"]:
        await show(event, t("no_leads", lang), back_menu_kb(lang), edit=edit)
        return
    pages = max(1, math.ceil(data["total"] / PAGE_SIZE))
    await show(event, leads_page(data["items"], data["total"], page, PAGE_SIZE, lang, qualified),
               leads_kb(data["items"], page, pages, qualified, cid, lang), edit=edit)


async def show_lead(event: Message | CallbackQuery, lead_id: str, lang: str, api: BackendClient,
                    edit: bool = True) -> None:
    d = await api.lead(event.from_user.id, lead_id)
    b = d["business"]
    kb = lead_kb(lead_id, lang, whatsapp_number(d.get("contacts", [])), b.get("website_url"))
    await show(event, lead_card(d, lang, await api.meta()), kb, edit=edit)


@router.message(Command("top"))
async def top_cmd(message: Message, state: FSMContext, lang: str, api: BackendClient, me: dict) -> None:
    await show_leads(message, lang, api, state=state)


@router.callback_query(F.data == "m:top")
async def top_cb(cb: CallbackQuery, state: FSMContext, lang: str, api: BackendClient) -> None:
    await show_leads(cb, lang, api, state=state)
    await cb.answer()


@router.callback_query(F.data.startswith("l:p:"))
async def page_cb(cb: CallbackQuery, state: FSMContext, lang: str, api: BackendClient) -> None:
    parts = cb.data.split(":")
    cid = parts[4] if len(parts) > 4 else None
    await show_leads(cb, lang, api, page=max(1, int(parts[2])), qualified=parts[3] == "1", cid=cid, state=state)
    await cb.answer()


@router.callback_query(F.data == "l:back")
async def back_cb(cb: CallbackQuery, state: FSMContext, lang: str, api: BackendClient) -> None:
    ctx = (await state.get_data()).get("leads_ctx") or {}
    await show_leads(cb, lang, api, page=ctx.get("page", 1), qualified=ctx.get("q", True), cid=ctx.get("cid"),
                     state=state)
    await cb.answer()


@router.callback_query(F.data.startswith("l:v:"))
async def view_cb(cb: CallbackQuery, state: FSMContext, lang: str, api: BackendClient) -> None:
    if await state.get_state() == NoteInput.body.state:  # "Cancel" on the note prompt
        await state.set_state(None)
    await show_lead(cb, cb.data.split(":")[2], lang, api)
    await cb.answer()


@router.callback_query(F.data.startswith("l:s:"))
async def status_menu(cb: CallbackQuery, lang: str, api: BackendClient) -> None:
    lead_id = cb.data.split(":")[2]
    b = (await api.lead(cb.from_user.id, lead_id))["business"]
    await show(cb, t("pick_status", lang, name=escape(b["name"])), crm_kb(lead_id, b.get("crm_status"), lang))
    await cb.answer()


@router.callback_query(F.data.startswith("l:st:"))
async def set_status(cb: CallbackQuery, lang: str, api: BackendClient) -> None:
    _, _, lead_id, status = cb.data.split(":", 3)
    if status not in BOT_CRM_STATUSES:
        await cb.answer(t("expired_button", lang), show_alert=True)
        return
    await api.update_lead(cb.from_user.id, lead_id, crm_status=status)
    await show_lead(cb, lead_id, lang, api)
    await cb.answer(t("status_saved", lang))


@router.callback_query(F.data.startswith("l:n:"))
async def note_prompt(cb: CallbackQuery, state: FSMContext, lang: str, api: BackendClient) -> None:
    lead_id = cb.data.split(":")[2]
    b = (await api.lead(cb.from_user.id, lead_id))["business"]
    await state.set_state(NoteInput.body)
    await state.update_data(note_lead=lead_id)
    await show(cb, t("ask_note", lang, name=escape(b["name"])), note_kb(lead_id, lang))
    await cb.answer()


@router.message(StateFilter(NoteInput.body), TEXT_INPUT)
async def note_text(message: Message, state: FSMContext, lang: str, api: BackendClient) -> None:
    lead_id = (await state.get_data()).get("note_lead")
    await state.set_state(None)
    if not lead_id:
        return
    await api.add_note(message.from_user.id, lead_id, message.text.strip()[:5000])
    await message.answer(t("note_saved", lang))
    await show_lead(message, lead_id, lang, api, edit=False)
