"""Platform admin: review new accounts from Telegram (same API as the dashboard, as the admin's linked account).

The backend sends each new signup to the admins with Approve / Reject / Details buttons (adm:ok, adm:no, adm:u);
/admin lists the accounts waiting for review and the possible duplicates.
"""
from html import escape

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.i18n import REJECT_REASONS, SIGNALS, num, t
from bot.keyboards.menus import admin_home_kb, admin_list_kb, admin_user_kb, reject_reasons_kb
from bot.services.api import ApiError, BackendClient
from bot.states.campaign import RejectReason
from bot.ui import show

router = Router(name="admin")
PAGE_SIZE = 6


def _flag(code: str | None) -> str:
    if not code or len(code) != 2 or not code.isalpha():
        return "—"
    return "".join(chr(0x1F1E6 + ord(c) - ord("A")) for c in code.upper()) + f" {code.upper()}"


def user_card(u: dict, lang: str) -> str:
    ws = u.get("workspace") or {}
    balance = "∞" if ws.get("billing_exempt") else num(ws.get("balance", 0))
    status = t(f"st_{u['approval_status']}", lang)
    if u.get("reviewed_by"):
        status += " " + t("reviewed_by", lang, who=escape(u["reviewed_by"]))
    text = t("user_card", lang, name=escape(u.get("full_name") or "—"), email=escape(u["email"]),
             phone=escape(u.get("phone") or "—"), nationality=_flag(u.get("nationality")),
             company=escape(ws.get("name") or "—"), created=(u.get("created_at") or "")[:10],
             ip=escape(u.get("signup_ip") or "—"), verified=t("yes" if u.get("email_verified_at") else "no", lang),
             balance=balance, status=status)
    if u.get("approval_status") == "rejected" and u.get("review_note"):
        text += "\n" + t("reject_reason_line", lang, reason=escape(u["review_note"]))
    dups = u.get("duplicates")
    if dups is None:
        return text
    if not dups:
        return text + "\n\n" + t("dups_none", lang)
    lines = [t("dups_title", lang, n=len(dups))]
    for d in dups[:6]:
        why = ", ".join(SIGNALS[k][1 if lang == "ar" else 0] for k in d["kinds"] if k in SIGNALS)
        state = " ❌" if d.get("approval_status") == "rejected" else ""
        lines.append(f"• {escape(d['email'])}{state}: {why}")
    if not any(d.get("strong") for d in dups):
        lines.append(t("weak_only", lang))
    return text + "\n\n" + "\n".join(lines)


def _is_admin(me: dict | None) -> bool:
    return bool((me or {}).get("is_superuser"))


async def show_home(event: Message | CallbackQuery, lang: str, api: BackendClient) -> None:
    s = await api.users_summary(event.from_user.id)
    await show(event, t("admin_home", lang, **s), admin_home_kb(s, lang))


@router.message(Command("admin"))
async def admin_cmd(message: Message, state: FSMContext, lang: str, api: BackendClient, me: dict) -> None:
    await state.set_state(None)
    if not _is_admin(me):
        await message.answer(t("admin_only", lang))
        return
    await show_home(message, lang, api)


async def _not_admin(cb: CallbackQuery, me: dict | None = None) -> bool:
    return not _is_admin(me)


@router.callback_query(F.data.startswith("adm:"), _not_admin)
async def admin_gate(cb: CallbackQuery, lang: str) -> None:
    """Turns away non-admins before any API call (the backend refuses them too)."""
    await cb.answer(t("admin_only", lang), show_alert=True)


@router.callback_query(F.data == "adm:home")
async def home_cb(cb: CallbackQuery, state: FSMContext, lang: str, api: BackendClient, me: dict) -> None:
    await state.set_state(None)
    await show_home(cb, lang, api)
    await cb.answer()


@router.callback_query(F.data.startswith("adm:list:"))
async def list_cb(cb: CallbackQuery, lang: str, api: BackendClient) -> None:
    _, _, which, page = cb.data.split(":")
    page = max(0, int(page))
    params = {"status": "pending"} if which == "p" else {"suspicious": "true"}
    data = await api.admin_users(cb.from_user.id, page=page + 1, page_size=PAGE_SIZE, **params)
    total = data.get("total", 0)
    if not total:
        await cb.answer(t("list_empty", lang), show_alert=True)
        return
    pages = max(1, -(-total // PAGE_SIZE))
    title = t("list_pending" if which == "p" else "list_suspects", lang, total=total)
    await show(cb, title, admin_list_kb(data["items"], which, page, pages, lang))
    await cb.answer()


async def _show_user(cb: CallbackQuery, lang: str, api: BackendClient, user_id: str, edit: bool = True) -> None:
    u = await api.admin_user(cb.from_user.id, user_id)
    await show(cb, user_card(u, lang), admin_user_kb(u, lang), edit=edit)


@router.callback_query(F.data.startswith("adm:u:"))
async def user_cb(cb: CallbackQuery, state: FSMContext, lang: str, api: BackendClient) -> None:
    await state.set_state(None)
    await _show_user(cb, lang, api, cb.data.split(":", 2)[2])
    await cb.answer()


async def _review(cb: CallbackQuery, lang: str, api: BackendClient, user_id: str, reason: str | None) -> None:
    """Approve (reason None) or reject, then show the updated card in place of the message the button was on."""
    try:
        if reason is None:
            u = await api.approve_user(cb.from_user.id, user_id)
        else:
            u = await api.reject_user(cb.from_user.id, user_id, reason)
    except ApiError as exc:
        if exc.code != "already_reviewed":
            raise
        await cb.answer(t("already_reviewed", lang), show_alert=True)
        await _show_user(cb, lang, api, user_id)
        return
    await show(cb, user_card(u, lang), admin_user_kb(u, lang))
    await cb.answer(t("approved_ok" if reason is None else "rejected_ok", lang))


@router.callback_query(F.data.startswith("adm:ok:"))
async def approve_cb(cb: CallbackQuery, lang: str, api: BackendClient) -> None:
    await _review(cb, lang, api, cb.data.split(":", 2)[2], None)


@router.callback_query(F.data.startswith("adm:no:"))
async def reject_cb(cb: CallbackQuery, lang: str) -> None:
    uid = cb.data.split(":", 2)[2]
    await show(cb, t("pick_reason", lang), reject_reasons_kb(uid, lang))
    await cb.answer()


@router.callback_query(F.data.startswith("adm:nr:"))
async def reason_cb(cb: CallbackQuery, state: FSMContext, lang: str, api: BackendClient) -> None:
    _, _, uid, key = cb.data.split(":")
    if key in REJECT_REASONS:
        await _review(cb, lang, api, uid, REJECT_REASONS[key])
        return
    await state.set_state(RejectReason.text)
    await state.update_data(reject_user=uid)
    await show(cb, t("type_reason", lang))
    await cb.answer()


@router.message(RejectReason.text, F.text)
async def reason_text(message: Message, state: FSMContext, lang: str, api: BackendClient) -> None:
    reason = message.text.strip()
    if len(reason) < 3 or reason.startswith("/"):
        await message.answer(t("type_reason", lang))
        return
    uid = (await state.get_data()).get("reject_user")
    await state.set_state(None)
    if not uid:  # the bot restarted mid-flow (memory storage): start again from the account card
        await message.answer(t("expired_button", lang))
        return
    try:
        u = await api.reject_user(message.from_user.id, uid, reason[:500])
    except ApiError as exc:
        if exc.code != "already_reviewed":
            raise
        await message.answer(t("already_reviewed", lang))
        return
    await message.answer(t("rejected_ok", lang) + "\n\n" + user_card(u, lang), reply_markup=admin_user_kb(u, lang))
