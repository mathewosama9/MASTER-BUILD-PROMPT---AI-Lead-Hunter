"""Telegram bot entry point.

Development: long polling (default when TELEGRAM_WEBHOOK_URL is empty).
Production: webhook with a secret token validated on every request.
"""
import asyncio
import logging
import sys

from aiogram.types import BotCommand

from bot.app import build_bot, build_dispatcher
from bot.config import get_settings
from bot.services.api import BackendClient

log = logging.getLogger("bot")

COMMANDS = [
    BotCommand(command="start", description="Main menu"),
    BotCommand(command="new", description="New campaign"),
    BotCommand(command="campaigns", description="My campaigns"),
    BotCommand(command="top", description="Top leads"),
    BotCommand(command="link", description="Link your account: /link CODE"),
    BotCommand(command="lang", description="Switch language EN/AR"),
    BotCommand(command="help", description="Help"),
]


def _storage():
    s = get_settings()
    try:
        from aiogram.fsm.storage.redis import RedisStorage

        return RedisStorage.from_url(s.redis_url)
    except Exception:  # noqa: BLE001 - redis extra missing: fall back to memory (wizard state not persisted)
        log.warning("Redis FSM storage unavailable; using in-memory storage")
        return None


async def run() -> None:
    s = get_settings()
    logging.basicConfig(level=s.log_level, stream=sys.stdout,
                        format='{"ts":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","message":"%(message)s"}')
    if not s.telegram_bot_token:
        log.error("TELEGRAM_BOT_TOKEN is not set; the bot cannot start. Configure it in .env.")
        # Stay alive without crash-looping so docker compose remains healthy; nothing to do.
        while True:
            await asyncio.sleep(3600)
    if not s.telegram_service_token:
        log.error("TELEGRAM_SERVICE_TOKEN is not set; the bot cannot authenticate to the backend.")
        sys.exit(1)
    api = BackendClient()
    bot = build_bot(s.telegram_bot_token)
    dp = build_dispatcher(api, _storage())
    await bot.set_my_commands(COMMANDS)
    try:
        if s.telegram_webhook_url:
            await _run_webhook(bot, dp)
        else:
            await bot.delete_webhook(drop_pending_updates=False)
            log.info("Starting long polling")
            await dp.start_polling(bot)
    finally:
        await api.close()
        await bot.session.close()


async def _run_webhook(bot, dp) -> None:
    from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
    from aiohttp import web

    s = get_settings()
    if not s.telegram_webhook_secret:
        raise SystemExit("TELEGRAM_WEBHOOK_SECRET is required in webhook mode")
    url = s.telegram_webhook_url.rstrip("/") + s.telegram_webhook_path
    await bot.set_webhook(url, secret_token=s.telegram_webhook_secret, drop_pending_updates=False)
    app = web.Application()
    # SimpleRequestHandler rejects requests whose X-Telegram-Bot-Api-Secret-Token does not match.
    SimpleRequestHandler(dispatcher=dp, bot=bot, secret_token=s.telegram_webhook_secret).register(
        app, path=s.telegram_webhook_path)
    app.router.add_get("/healthz", lambda _: web.json_response({"status": "ok"}))
    setup_application(app, dp, bot=bot)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, s.webhook_host, s.webhook_port).start()
    log.info("Webhook listening on %s:%s%s", s.webhook_host, s.webhook_port, s.telegram_webhook_path)
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(run())
