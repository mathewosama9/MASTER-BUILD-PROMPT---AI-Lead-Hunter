from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.base import BaseStorage
from aiogram.fsm.storage.memory import MemoryStorage

from bot.handlers import billing, campaigns, errors, leads, menu, wizard
from bot.middleware import AuthMiddleware
from bot.services.api import BackendClient


def build_dispatcher(api: BackendClient, storage: BaseStorage | None = None) -> Dispatcher:
    dp = Dispatcher(storage=storage or MemoryStorage())
    auth = AuthMiddleware(api)
    dp.message.outer_middleware(auth)
    dp.callback_query.outer_middleware(auth)
    # Commands first so /start, /cancel… work from inside any flow; the wizard holds the plain-text search
    # catch-all; errors last (stale buttons and the error handler).
    dp.include_routers(menu.router, campaigns.router, leads.router, billing.router, wizard.router, errors.router)
    dp.workflow_data["auth"] = auth
    return dp


def build_bot(token: str) -> Bot:
    return Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML, link_preview_is_disabled=True))
