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

COMMANDS = {
    "en": [("start", "Main menu"), ("new", "New search"), ("campaigns", "My searches"), ("top", "Best leads"),
           ("balance", "My credits"), ("lang", "العربية / English"), ("help", "How it works")],
    "ar": [("start", "القائمة الرئيسية"), ("new", "بحث جديد"), ("campaigns", "عمليات البحث"),
           ("top", "أفضل العملاء"), ("balance", "رصيدي"), ("lang", "English / العربية"), ("help", "إزاي بيشتغل")],
}
DESCRIPTION = {
    "en": "Rasd finds businesses that need what you sell — with their phone, WhatsApp and email — and tells you "
          "why each one fits. Link your account from the dashboard to start.",
    "ar": "رصد بيلاقيلك الشركات اللي محتاجة خدمتك — بتليفوناتها وواتسابها وإيميلاتها — وبيقولك ليه كل واحدة "
          "مناسبة. اربط حسابك من لوحة التحكم عشان تبدأ.",
}
SHORT_DESCRIPTION = {"en": "Ready clients for your business, on Telegram.", "ar": "عملاء جاهزين لشغلك، على تيليجرام."}


async def _setup_profile(bot) -> None:
    """Menu commands and the bot's About texts in both languages (Telegram picks by the user's app language)."""
    for lang, items in COMMANDS.items():
        code = None if lang == "en" else lang
        try:
            await bot.set_my_commands([BotCommand(command=c, description=d) for c, d in items], language_code=code)
            await bot.set_my_description(DESCRIPTION[lang], language_code=code)
            await bot.set_my_short_description(SHORT_DESCRIPTION[lang], language_code=code)
        except Exception:  # cosmetic; never block the bot from starting
            log.warning("could not update the bot profile for %s", lang, exc_info=True)


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
    await _setup_profile(bot)
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
    if s.webhook_socket:
        await web.UnixSite(runner, s.webhook_socket).start()
        log.info("Webhook listening on %s%s", s.webhook_socket, s.telegram_webhook_path)
    else:
        await web.TCPSite(runner, s.webhook_host, s.webhook_port).start()
        log.info("Webhook listening on %s:%s%s", s.webhook_host, s.webhook_port, s.telegram_webhook_path)
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(run())
