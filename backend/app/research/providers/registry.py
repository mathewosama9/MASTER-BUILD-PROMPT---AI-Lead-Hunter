"""Provider registry. New sources plug in here; the pipeline never imports concrete adapters."""

from app.core.config import get_settings
from app.research.providers.base import DiscoveryProvider, ProviderInfo
from app.research.providers.brave import BraveSearchProvider
from app.research.providers.demo import DemoProvider
from app.research.providers.google_maps import GoogleMapsProvider
from app.research.providers.hunter import HunterDiscoverProvider
from app.research.providers.imported import ImportProvider
from app.research.providers.osm import OsmProvider
from app.research.providers.social import FacebookProvider, ManualProvider, XProvider

_DISCOVERY: dict[str, DiscoveryProvider] = {}


def register(provider: DiscoveryProvider) -> None:
    _DISCOVERY[provider.info.key] = provider


def get_discovery_provider(key: str) -> DiscoveryProvider:
    if key not in _DISCOVERY:
        raise KeyError(f"Unknown discovery provider: {key}")
    return _DISCOVERY[key]


def discovery_providers() -> list[DiscoveryProvider]:
    return list(_DISCOVERY.values())


for _p in (
    DemoProvider(),
    OsmProvider(),
    GoogleMapsProvider(),
    BraveSearchProvider(),
    HunterDiscoverProvider(),
    XProvider(),
    FacebookProvider(),
    ManualProvider(),
    ImportProvider(),
):
    register(_p)


# Non-discovery integrations shown in Settings. Credentials come from env first, then encrypted DB storage.
INTEGRATIONS: dict[str, ProviderInfo] = {
    "anthropic": ProviderInfo(
        "anthropic",
        "Anthropic Claude",
        "ai",
        "Preferred AI provider for analysis and pitches.",
        ["api_key"],
        "https://docs.claude.com",
    ),
    "openai": ProviderInfo("openai", "OpenAI", "ai", "Optional alternative AI provider.", ["api_key"]),
    "deepseek": ProviderInfo(
        "deepseek",
        "DeepSeek",
        "ai",
        "AI analysis, pitches and NL targeting via the DeepSeek API (JSON output validated against the schema).",
        ["api_key"],
        "https://api-docs.deepseek.com",
    ),
    "firecrawl": ProviderInfo(
        "firecrawl",
        "Firecrawl",
        "enrichment",
        "Optional managed crawling (not required; built-in crawler is used by default).",
        ["api_key"],
    ),
    "telegram": ProviderInfo(
        "telegram", "Telegram Bot", "messaging", "Bot token for the Telegram interface.", ["bot_token"]
    ),
    "google_sheets": ProviderInfo(
        "google_sheets",
        "Google Sheets",
        "export",
        "Service-account JSON for exporting leads to Sheets.",
        ["credentials_json"],
    ),
    "n8n": ProviderInfo(
        "n8n", "n8n Webhook", "webhook", "Optional webhook fired on campaign completion.", ["webhook_url"]
    ),
    "crm_webhook": ProviderInfo(
        "crm_webhook", "CRM Webhook", "webhook", "Optional webhook receiving qualified leads.", ["webhook_url"]
    ),
}

# Maps provider key -> {credential field: settings attribute} for env-based credentials.
ENV_CREDENTIALS: dict[str, dict[str, str]] = {
    "brave": {"api_key": "brave_api_key"},
    "hunter": {"api_key": "hunter_api_key"},
    "x": {"bearer_token": "x_bearer_token"},
    "facebook": {"access_token": "facebook_access_token"},
    "anthropic": {"api_key": "anthropic_api_key"},
    "openai": {"api_key": "openai_api_key"},
    "deepseek": {"api_key": "deepseek_api_key"},
    "firecrawl": {"api_key": "firecrawl_api_key"},
    "telegram": {"bot_token": "telegram_bot_token"},
    "google_sheets": {"credentials_json": "google_sheets_credentials_json"},
    "n8n": {"webhook_url": "n8n_webhook_url"},
    "crm_webhook": {"webhook_url": "crm_webhook_url"},
}


def env_credentials(key: str) -> dict[str, str]:
    settings = get_settings()
    out: dict[str, str] = {}
    for field, attr in ENV_CREDENTIALS.get(key, {}).items():
        value = getattr(settings, attr, None)
        if value:
            out[field] = value
    return out
