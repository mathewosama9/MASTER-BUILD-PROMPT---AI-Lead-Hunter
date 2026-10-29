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
from bot.services.api import ApiError, BackendClient

OPEN_COMMANDS = ("/link", "/help", "/lang")
LANG_OVERRIDE: dict[int, str] = {}
_cache: dict[int, tuple[float, dict]] = {}
CACHE_SECONDS = 60


def user_lang(user_id: int, language_code: str | None) -> str:
    if user_id in LANG_OVERRIDE:
        return LANG_OVERRIDE[user_id]
    return "ar" if (language_code or "").startswith("ar") else "en"


def _saved_lang(user_id: int, me: dict, fallback: str) -> str:
    """A /lang choice made in this process wins; otherwise the language stored on the linked account."""
    if user_id in LANG_OVERRIDE:
        return LANG_OVERRIDE[user_id]
    return me.get("locale") if me.get("locale") in ("ar", "en") else fallback


def invalidate(user_id: int) -> None:
    _cache.pop(user_id, None)


class AuthMiddleware(BaseMiddleware):
    def __init__(self, api: BackendClient) -> None:
        self.api = api

    async def __call__(self, handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
                       event: TelegramObject, data: dict[str, Any]) -> Any:
        user = getattr(event, "from_user", None)
        if user is None:
            return None
        lang = user_lang(user.id, user.language_code)
        data["lang"] = lang
        data["api"] = self.api
        if isinstance(event, Message) and event.text and event.text.split()[0].split("@")[0] in OPEN_COMMANDS:
            return await handler(event, data)
        if isinstance(event, Message) and event.chat.type != "private":
            return None  # operate in private chats only
        cached = _cache.get(user.id)
        if cached and cached[0] > time.monotonic():
            data["me"] = cached[1]
            data["lang"] = _saved_lang(user.id, cached[1], lang)
            return await handler(event, data)
        try:
            me = await self.api.whoami(user.id)
        except ApiError as exc:
            text = t("not_linked", lang)
            if exc.status == 403:
                try:
                    status = (await self.api.json("POST", "/telegram/status", None,
                                                  params={"telegram_user_id": user.id}))["status"]
                    if status == "pending":
                        text = t("pending", lang)
                except ApiError:
                    pass
            elif exc.status >= 500 or exc.status == 401:
                text = t("error", lang, msg="backend unavailable")
            if isinstance(event, CallbackQuery):
                await event.answer(text[:190], show_alert=True)
            elif isinstance(event, Message):
                await event.answer(text)
            return None
        _cache[user.id] = (time.monotonic() + CACHE_SECONDS, me)
        data["me"] = me
        data["lang"] = _saved_lang(user.id, me, lang)
        return await handler(event, data)
