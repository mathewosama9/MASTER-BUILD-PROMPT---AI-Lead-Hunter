from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.base import BaseStorage
from aiogram.fsm.storage.memory import MemoryStorage

from bot.handlers import menu, wizard
from bot.middleware import AuthMiddleware
from bot.services.api import BackendClient


def build_dispatcher(api: BackendClient, storage: BaseStorage | None = None) -> Dispatcher:
    dp = Dispatcher(storage=storage or MemoryStorage())
    auth = AuthMiddleware(api)
    dp.message.outer_middleware(auth)
    dp.callback_query.outer_middleware(auth)
    # Wizard first so its state-filtered text handlers win over generic commands.
    dp.include_router(wizard.router)
    dp.include_router(menu.router)
    dp.workflow_data["auth"] = auth
    return dp


def build_bot(token: str) -> Bot:
    return Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
