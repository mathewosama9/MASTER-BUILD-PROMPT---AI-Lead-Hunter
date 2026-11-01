"""Access control: only approved, linked Telegram accounts reach the main handlers.

Authorization is enforced by the backend on every API call (service token + Telegram user id). This middleware
only provides a friendly early answer and the user's language.
"""
import time
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from bot.i18n import t
from bot.keyboards.menus import unlinked_kb
from bot.services.api import ApiError, BackendClient

OPEN_COMMANDS = ("/link", "/help", "/lang")
LANG_OVERRIDE: dict[int, str] = {}
_cache: dict[int, tuple[float, dict]] = {}
CACHE_SECONDS = 60


def user_lang(user_id: int, language_code: str | None) -> str:
    if user_id in LANG_OVERRIDE:
        return LANG_OVERRIDE[user_id]
    cached = _cache.get(user_id)
    if cached and cached[1].get("locale") in ("ar", "en"):
        return cached[1]["locale"]
    return "ar" if (language_code or "").startswith("ar") else "en"


def _saved_lang(user_id: int, me: dict, fallback: str) -> str:
    """A /lang choice made in this process wins; otherwise the language stored on the linked account."""
    if user_id in LANG_OVERRIDE:
        return LANG_OVERRIDE[user_id]
    return me.get("locale") if me.get("locale") in ("ar", "en") else fallback


def invalidate(user_id: int) -> None:
    _cache.pop(user_id, None)


def _is_open(event: TelegramObject) -> bool:
    """Commands that work before linking: /link, /help, /lang and the /start CODE deep link."""
    if not isinstance(event, Message) or not event.text:
        return False
    parts = event.text.split()
    command = parts[0].split("@")[0]
    return command in OPEN_COMMANDS or (command == "/start" and len(parts) > 1)


class AuthMiddleware(BaseMiddleware):
    def __init__(self, api: BackendClient) -> None:
        self.api = api

    async def __call__(self, handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
                       event: TelegramObject, data: dict[str, Any]) -> Any:
        user = getattr(event, "from_user", None)
        if user is None:
            return None
        chat = event.chat if isinstance(event, Message) else getattr(event.message, "chat", None)
        if chat is not None and chat.type != "private":
            return None  # operate in private chats only
        lang = user_lang(user.id, user.language_code)
        data["lang"] = lang
        data["api"] = self.api
        if _is_open(event):
            return await handler(event, data)
        cached = _cache.get(user.id)
        if cached and cached[0] > time.monotonic():
            data["me"] = cached[1]
            data["lang"] = _saved_lang(user.id, cached[1], lang)
            return await handler(event, data)
        try:
            me = await self.api.whoami(user.id)
        except ApiError as exc:
            await self._refuse(event, exc, lang, user.id)
            return None
        _cache[user.id] = (time.monotonic() + CACHE_SECONDS, me)
        data["me"] = me
        data["lang"] = _saved_lang(user.id, me, lang)
        return await handler(event, data)

    async def _refuse(self, event: TelegramObject, exc: ApiError, lang: str, uid: int) -> None:
        text, kb = t("not_linked", lang), unlinked_kb(lang)
        if exc.status == 403:
            try:
                if await self.api.link_status(uid) == "pending":
                    text, kb = t("pending", lang), None
            except ApiError:
                pass
        elif exc.status >= 500 or exc.status == 401:
            text, kb = t("backend_down", lang), None
        if isinstance(event, CallbackQuery):
            short = t("not_linked_short", lang) if text == t("not_linked", lang) else text
            await event.answer(short[:190], show_alert=True)
        elif isinstance(event, Message):
            await event.answer(text, reply_markup=kb)
