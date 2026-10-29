"""Brave Search API discovery adapter (official API: https://api.search.brave.com)."""

import logging

import httpx

from app.core.config import get_settings
from app.models.enums import ProviderStatus
from app.research.catalog import COUNTRIES
from app.research.enrichment.normalize import business_domain, homepage_url
from app.research.providers.base import (
    BusinessCandidate,
    ProviderContext,
    ProviderError,
    ProviderInfo,
    ProviderState,
    RateLimited,
    SearchQuery,
)
from app.research.providers.queries import build_search_queries

log = logging.getLogger(__name__)

BRAVE_URL = "https://api.search.brave.com/res/v1/web/search"
PAGE_SIZE = 20
MAX_OFFSET = 9  # Brave allows offset 0..9 pages


class BraveSearchProvider:
    info = ProviderInfo(
        key="brave",
        name="Brave Search",
        kind="discovery",
        description="General web search via the official Brave Search API.",
        requires=["api_key"],
        docs_url="https://api-dashboard.search.brave.com/app/documentation/web-search/get-started",
    )

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport

    def state(self, ctx: ProviderContext) -> ProviderState:
        if not ctx.credentials.get("api_key"):
            return ProviderState(ProviderStatus.REQUIRES_API_KEY, "Set BRAVE_API_KEY or add a key in Settings.")
        return ProviderState(ProviderStatus.CONNECTED)

    async def _request(self, client: httpx.AsyncClient, ctx: ProviderContext, params: dict) -> dict:
        resp = await client.get(BRAVE_URL, params=params)
        cost = get_settings().cost_brave_per_request
        if resp.status_code == 429:
            await ctx.record_usage(self.info.key, "web_search", 1, 0.0, False, 429)
            retry_after = resp.headers.get("retry-after") or resp.headers.get("x-ratelimit-reset")
            raise RateLimited(
                "Brave Search rate limit reached", retry_after=float(retry_after.split(",")[0]) if retry_after else None
            )
        if resp.status_code in (401, 403):
            await ctx.record_usage(self.info.key, "web_search", 1, 0.0, False, resp.status_code)
            raise ProviderError("Brave Search rejected the API key", status_code=resp.status_code)
        if resp.status_code >= 400:
            await ctx.record_usage(self.info.key, "web_search", 1, 0.0, False, resp.status_code)
            raise ProviderError(
                f"Brave Search error {resp.status_code}",
                retryable=resp.status_code >= 500,
                status_code=resp.status_code,
            )
        await ctx.record_usage(self.info.key, "web_search", 1, cost, True, resp.status_code)
        return resp.json()

    def _client(self, ctx: ProviderContext) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=15.0,
            transport=self._transport,
            headers={"Accept": "application/json", "X-Subscription-Token": ctx.credentials.get("api_key", "")},
        )

    async def search_businesses(self, query: SearchQuery, ctx: ProviderContext) -> list[BusinessCandidate]:
        state = self.state(ctx)
        if state.status != ProviderStatus.CONNECTED:
            raise ProviderError(state.detail or "Brave Search not configured")
        country = COUNTRIES.get(query.country.upper())
        brave_country = country["brave_country"] if country else "ALL"
        queries = build_search_queries(query, max_queries=int(ctx.settings.get("max_queries", 8)))
        found: dict[str, BusinessCandidate] = {}
        async with self._client(ctx) as client:
            for q in queries:
                for page in range(0, MAX_OFFSET + 1):
                    params = {
                        "q": q,
                        "count": PAGE_SIZE,
                        "offset": page,
                        "country": brave_country,
                        "search_lang": "ar" if any("؀" <= c <= "ۿ" for c in q) else "en",
                        "safesearch": "moderate",
                        "result_filter": "web",
                    }
                    data = await self._request(client, ctx, params)
                    results = (data.get("web") or {}).get("results") or []
                    for r in results:
                        cand = self._to_candidate(r, query)
                        if cand and cand.website_url:
                            key = business_domain(cand.website_url) or cand.website_url
                            found.setdefault(key, cand)
                    if len(found) >= query.limit or not (data.get("query") or {}).get("more_results_available"):
                        break
                if len(found) >= query.limit:
                    break
        return list(found.values())[: query.limit]

    def _to_candidate(self, r: dict, query: SearchQuery) -> BusinessCandidate | None:
        url = r.get("url")
        if not url:
            return None
        domain = business_domain(url)
        if domain is None:
            return None  # social/directory hit; not the business's own site
        profile = r.get("profile") or {}
        title = (r.get("title") or "").strip()
        name = (profile.get("name") or title.split(" | ")[0].split(" - ")[0]).strip() or domain
        return BusinessCandidate(
            name=name[:300],
            website_url=homepage_url(url),
            industry=query.industry,
            country=query.country,
            city=query.city,
            description=_strip_tags(r.get("description")),
            source_provider=self.info.key,
            source_url=url,
            source_title=title or None,
            raw={"title": title, "description": r.get("description"), "age": r.get("age")},
        )

    async def test_connection(self, ctx: ProviderContext) -> ProviderState:
        state = self.state(ctx)
        if state.status != ProviderStatus.CONNECTED:
            return state
        try:
            async with self._client(ctx) as client:
                await self._request(client, ctx, {"q": "test", "count": 1})
            return ProviderState(ProviderStatus.CONNECTED, "Brave Search responded successfully.")
        except RateLimited as exc:
            return ProviderState(ProviderStatus.RATE_LIMITED, str(exc))
        except (ProviderError, httpx.HTTPError) as exc:
            return ProviderState(ProviderStatus.ERROR, str(exc))


def _strip_tags(text: str | None) -> str | None:
    if not text:
        return None
    import re

    return re.sub(r"<[^>]+>", "", text).strip() or None
