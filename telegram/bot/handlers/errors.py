"""Last-resort handlers: friendly translated errors, stale buttons and the no-op pager label."""
import logging
from contextlib import suppress

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, ErrorEvent

from bot.i18n import t
from bot.middleware import user_lang
from bot.services.api import ApiError
from bot.ui import credit_message

log = logging.getLogger("bot.errors")
router = Router(name="errors")


@router.callback_query(F.data == "w:noop")
async def noop(cb: CallbackQuery) -> None:
    await cb.answer()


@router.callback_query()
async def stale_button(cb: CallbackQuery, lang: str) -> None:
    """A button from a finished wizard step or an old message."""
    await cb.answer(t("expired_button", lang), show_alert=True)


@router.error()
async def on_error(event: ErrorEvent) -> bool:
    exc, upd = event.exception, event.update
    cb, msg = upd.callback_query, upd.message
    if isinstance(exc, TelegramBadRequest) and "not modified" in str(exc):
        if cb:
            with suppress(TelegramBadRequest):
                await cb.answer()
        return True
    user = (cb or msg).from_user if (cb or msg) else None
    lang = user_lang(user.id, user.language_code) if user else "en"
    if isinstance(exc, ApiError):
        if exc.status >= 500:
            text = t("backend_down", lang)
        else:
            text = credit_message(exc.code, lang) or t("error", lang, msg=exc.message)
        log.info("backend refused a bot request", extra={"status": exc.status, "code": exc.code})
    else:
        log.exception("bot handler failed", exc_info=exc)
        text = t("error_generic", lang)
    with suppress(TelegramBadRequest):
        if cb:
            await cb.answer(text[:190], show_alert=True)
        elif msg:
            await msg.answer(text)
    return True
