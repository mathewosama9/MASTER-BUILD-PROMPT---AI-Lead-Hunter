"""The user's searches: paged list, card with live progress, and actions (also used by worker notifications)."""
import math

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from bot.formatting import campaign_card, campaigns_list
from bot.handlers.leads import show_leads
from bot.i18n import t
from bot.keyboards.menus import campaign_kb, campaigns_kb, main_menu
from bot.services.api import BackendClient
from bot.ui import show

router = Router(name="campaigns")
PAGE_SIZE = 6


async def show_campaigns(event: Message | CallbackQuery, lang: str, api: BackendClient, page: int = 1) -> None:
    data = await api.campaigns(event.from_user.id, page=page, page_size=PAGE_SIZE)
    if not data["items"]:
        await show(event, t("no_campaigns", lang), main_menu(lang))
        return
    pages = max(1, math.ceil(data["total"] / PAGE_SIZE))
    await show(event, campaigns_list(data["items"], data["total"], lang), campaigns_kb(data["items"], page, pages, lang))


@router.message(Command("campaigns"))
async def campaigns_cmd(message: Message, lang: str, api: BackendClient, me: dict) -> None:
    await show_campaigns(message, lang, api)


@router.callback_query(F.data == "m:mine")
async def mine_cb(cb: CallbackQuery, lang: str, api: BackendClient) -> None:
    await show_campaigns(cb, lang, api)
    await cb.answer()


@router.callback_query(F.data.startswith("c:list:"))
async def list_cb(cb: CallbackQuery, lang: str, api: BackendClient) -> None:
    await show_campaigns(cb, lang, api, page=max(1, int(cb.data.split(":")[2])))
    await cb.answer()


@router.callback_query(F.data.startswith("c:"))
async def campaign_action(cb: CallbackQuery, state: FSMContext, lang: str, api: BackendClient) -> None:
    _, action, cid = cb.data.split(":", 2)
    uid = cb.from_user.id
    meta = await api.meta()
    if action in ("pause", "cancel", "resume", "retry"):
        c = await api.action(uid, cid, action)
        await show(cb, campaign_card(c, lang, meta), campaign_kb(cid, c["status"], lang))
        await cb.answer(t("done_action", lang))
    elif action in ("view", "prog"):
        c = await api.campaign(uid, cid)
        await show(cb, campaign_card(c, lang, meta), campaign_kb(cid, c["status"], lang))
        await cb.answer(t("updated", lang) if action == "prog" else None)
    elif action in ("res", "top"):
        # A new message, so a finished-search notification stays in the chat.
        await show_leads(cb, lang, api, page=1, qualified=action == "top", cid=cid, edit=False,
                         state=state)
        await cb.answer()
    elif action == "csv":
        content = await api.campaign_csv(uid, cid)
        await cb.message.answer_document(BufferedInputFile(content, filename=f"rasd-{cid[:8]}.csv"),
                                         caption=t("export_caption", lang))
        await cb.answer()
    else:
        await cb.answer(t("expired_button", lang), show_alert=True)
