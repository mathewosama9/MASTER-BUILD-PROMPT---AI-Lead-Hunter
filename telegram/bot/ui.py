"""Shared message helpers: navigation edits the message the button is on, so the chat does not fill up."""
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from bot.i18n import t

CREDIT_CODES = {"insufficient_credits": "msg_no_credits", "trial_expired": "msg_trial_expired",
                "email_unverified": "msg_email_unverified"}


async def show(event: Message | CallbackQuery, text: str, kb: InlineKeyboardMarkup | None = None,
               edit: bool = True) -> Message:
    """Edit the callback's message in place (when `edit`), else send a new message. Returns the shown message."""
    if isinstance(event, CallbackQuery):
        msg = event.message
        if edit and isinstance(msg, Message) and msg.text is not None:
            try:
                await msg.edit_text(text, reply_markup=kb)
                return msg
            except TelegramBadRequest as exc:
                if "not modified" in str(exc):
                    return msg
        # Old, media or inaccessible message: send a fresh one (chats are private, so chat id == user id).
        return await event.bot.send_message(event.from_user.id, text, reply_markup=kb)
    return await event.answer(text, reply_markup=kb)


def credit_message(code: str | None, lang: str) -> str | None:
    key = CREDIT_CODES.get(code or "")
    return t(key, lang) if key else None
