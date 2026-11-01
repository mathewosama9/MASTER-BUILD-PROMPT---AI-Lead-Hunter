from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class BotSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    telegram_bot_token: str = ""
    # Shared secret the bot uses to call the backend on behalf of linked Telegram users.
    telegram_service_token: str = ""
    api_base_url: str = "http://localhost:8000/api/v1"
    # Unix socket of the API (shared hosting); when set, api_base_url only supplies the path prefix.
    api_socket: str = ""
    frontend_url: str = "http://localhost:3000"
    # Webhook mode (production). Leave TELEGRAM_WEBHOOK_URL empty to use long polling (development).
    telegram_webhook_url: str = ""
    telegram_webhook_secret: str = ""
    telegram_webhook_path: str = "/telegram/webhook"
    webhook_host: str = "0.0.0.0"  # bound inside the container network
    webhook_port: int = 8081
    # Listen on a Unix socket instead of webhook_host:webhook_port (shared hosting, behind the site's proxy).
    webhook_socket: str = ""
    redis_url: str = "redis://localhost:6379/2"
    log_level: str = "INFO"


@lru_cache
def get_settings() -> BotSettings:
    return BotSettings()
