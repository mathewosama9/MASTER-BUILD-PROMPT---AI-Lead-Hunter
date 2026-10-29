from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-driven configuration. Secrets are never hardcoded."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "AI Lead Hunter"
    environment: Literal["development", "test", "production"] = "development"
    debug: bool = False
    log_level: str = "INFO"

    # Demo mode enables the fictional demo provider/analyzer. Real providers stay available.
    demo_mode: bool = True

    database_url: str = "postgresql+asyncpg://leadhunter:leadhunter@localhost:5432/leadhunter"
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str | None = None
    celery_result_backend: str | None = None
    celery_task_always_eager: bool = False

    secret_key: str = Field(default="change-me-in-production-please-32b", min_length=16)
    # Fernet key used to encrypt provider secrets stored in the DB. Derived from secret_key when unset.
    encryption_key: str | None = None
    access_token_minutes: int = 60 * 12
    cookie_secure: bool = False
    cookie_domain: str | None = None
    # Comma-separated in env (NoDecode: parsed by the validator below, not as JSON).
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:3000"]
    frontend_url: str = "http://localhost:3000"

    # Service-to-service token used by the Telegram bot to call the API on behalf of linked users.
    telegram_service_token: str | None = None
    telegram_bot_token: str | None = None
    telegram_webhook_secret: str | None = None
    telegram_bot_username: str | None = None

    # Provider credentials (env takes precedence over encrypted DB-stored values).
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-opus-5-5"
    openai_api_key: str | None = None
    openai_model: str = "gpt-4.1-mini"
    # Preferred AI provider; the others are used as fallbacks when they have a key.
    ai_provider: Literal["anthropic", "openai", "deepseek"] = "anthropic"
    deepseek_api_key: str | None = None
    deepseek_model: str = "deepseek-flash"
    deepseek_base_url: str = "https://api.deepseek.com"
    ai_max_tokens: int = 16000
    brave_api_key: str | None = None
    hunter_api_key: str | None = None
    firecrawl_api_key: str | None = None
    x_bearer_token: str | None = None
    facebook_access_token: str | None = None
    n8n_webhook_url: str | None = None
    crm_webhook_url: str | None = None
    google_sheets_credentials_json: str | None = None

    # Crawler limits
    crawler_user_agent: str = "AILeadHunterBot/0.1 (+https://example.com/bot)"
    crawler_timeout_seconds: float = 10.0
    crawler_max_bytes: int = 1_500_000
    crawler_max_redirects: int = 4

    # OpenStreetMap (free, keyless). Nominatim's usage policy requires an identifying User-Agent with contact info.
    # Comma-separated Overpass endpoints, tried in order when one is overloaded (5xx/429).
    osm_overpass_url: str = (
        "https://overpass-api.de/api/interpreter,"
        "https://overpass.private.coffee/api/interpreter,"
        "https://overpass.kumi.systems/api/interpreter"
    )
    osm_city_radius_km: float = 25.0
    osm_nominatim_url: str = "https://nominatim.openstreetmap.org"
    # Optional real contact address added to the User-Agent (placeholder addresses get blocked by Nominatim).
    osm_contact_email: str = ""

    # Direct browser scraping (Google Maps discovery, public social profile pages). Off unless enabled.
    # Limits: no account login, no captcha solving, no proxy rotation; a block stops the source cleanly.
    scraping_enabled: bool = False
    scraper_headless: bool = True
    scraper_max_places_per_campaign: int = 60
    scraper_delay_min: float = 2.0
    scraper_delay_max: float = 5.0
    scraper_page_timeout_seconds: float = 30.0
    social_enrichment_enabled: bool = True
    social_profiles_per_business: int = 4
    # Search for a business's social profiles by name when it published no link (one web search per missing
    # platform) through the official Brave Search API; needs a Brave key. Capped per workspace per day.
    social_search_enabled: bool = False
    social_search_platforms: str = "instagram,facebook,tiktok,snapchat"
    social_search_daily_limit: int = 200
    # Login browser (dashboard "Connect" for linked accounts): internal control URL and the noVNC URL the
    # user's browser loads. Keep the noVNC port bound to localhost or behind authenticated HTTPS.
    login_browser_url: str = "http://login-browser:7900"
    login_browser_public_url: str = "http://localhost:6080"

    # Free email domain check (DNS MX). Never marks an address "verified".
    email_mx_check: bool = True

    # Cost estimates (USD) used for budget tracking when providers do not return cost.
    cost_brave_per_request: float = 0.005
    cost_hunter_per_request: float = 0.01
    cost_ai_input_per_mtok: float = 4.0
    cost_ai_output_per_mtok: float = 20.0
    # DeepSeek pricing estimate (USD per million tokens); check the DeepSeek pricing page and adjust.
    cost_deepseek_input_per_mtok: float = 0.30
    cost_deepseek_output_per_mtok: float = 1.20

    rate_limit_default: str = "120/minute"
    data_retention_days: int = 365

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, v: object) -> object:
        if isinstance(v, str) and not v.startswith("["):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    @property
    def broker_url(self) -> str:
        return self.celery_broker_url or self.redis_url

    @property
    def result_backend(self) -> str:
        return self.celery_result_backend or self.redis_url

    @property
    def sync_database_url(self) -> str:
        return self.database_url.replace("+asyncpg", "+psycopg").replace("+aiosqlite", "")


@lru_cache
def get_settings() -> Settings:
    return Settings()
