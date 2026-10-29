"""X (Twitter) and Facebook adapters.

Both use only official, authorized APIs. Facebook has no public business-search API for third parties,
so it reports UNSUPPORTED for discovery and instead accepts manually supplied page URLs, which are
recorded as candidates for permitted analysis of the linked business website (no scraping of Facebook).
"""

import httpx

from app.models.enums import ProviderStatus
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

X_API = "https://api.x.com/2"


class XProvider:
    info = ProviderInfo(
        key="x",
        name="X API",
        kind="discovery",
        description="Business accounts via the official X API v2 recent search (pay-per-use: requires X API credits).",
        requires=["bearer_token"],
        docs_url="https://docs.x.com/x-api/introduction",
    )

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport

    def state(self, ctx: ProviderContext) -> ProviderState:
        if not ctx.credentials.get("bearer_token"):
            return ProviderState(ProviderStatus.REQUIRES_API_KEY, "Set X_BEARER_TOKEN (app Bearer Token).")
        return ProviderState(ProviderStatus.CONNECTED)

    def _client(self, ctx: ProviderContext) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=15.0,
            transport=self._transport,
            headers={"Authorization": f"Bearer {ctx.credentials.get('bearer_token', '')}"},
        )

    async def _get(self, client: httpx.AsyncClient, ctx: ProviderContext, path: str, params: dict) -> dict:
        resp = await client.get(f"{X_API}{path}", params=params)
        ok = resp.status_code < 400
        await ctx.record_usage(self.info.key, path.strip("/").replace("/", "_"), 1, 0.0, ok, resp.status_code)
        if resp.status_code == 429:
            raise RateLimited(
                "X API rate limit / monthly cap reached",
                retry_after=float(resp.headers.get("x-rate-limit-reset", 0)) or None,
            )
        if resp.status_code == 401:
            raise ProviderError("X API rejected the Bearer Token (invalid or revoked)", status_code=401)
        if resp.status_code == 402:
            raise ProviderError(
                "X API credits depleted: add credits under Billing → Credits in the X Developer Console",
                status_code=402,
            )
        if resp.status_code == 403:
            raise ProviderError("X API access tier does not include this endpoint", status_code=403)
        if not ok:
            raise ProviderError(
                f"X API error {resp.status_code}", retryable=resp.status_code >= 500, status_code=resp.status_code
            )
        return resp.json()

    async def search_businesses(self, query: SearchQuery, ctx: ProviderContext) -> list[BusinessCandidate]:
        if self.state(ctx).status != ProviderStatus.CONNECTED:
            raise ProviderError("X API is not configured")
        found: dict[str, BusinessCandidate] = {}
        async with self._client(ctx) as client:
            for q in build_search_queries(query, max_queries=3):
                params = {
                    "query": f"({q.split(' -')[0]}) has:links -is:retweet",
                    "max_results": 50,
                    "expansions": "author_id",
                    "user.fields": "name,username,description,url,entities,location,verified",
                }
                data = await self._get(client, ctx, "/tweets/search/recent", params)
                for user in (data.get("includes") or {}).get("users", []):
                    url = _expanded_user_url(user)
                    domain = business_domain(url)
                    if not domain or domain in found:
                        continue
                    found[domain] = BusinessCandidate(
                        name=user.get("name") or domain,
                        website_url=homepage_url(url) if url else None,
                        industry=query.industry,
                        country=query.country,
                        city=query.city,
                        description=user.get("description"),
                        source_provider=self.info.key,
                        source_url=f"https://x.com/{user.get('username')}",
                        raw={"username": user.get("username"), "location": user.get("location")},
                    )
                if len(found) >= query.limit:
                    break
        return list(found.values())[: query.limit]

    async def test_connection(self, ctx: ProviderContext) -> ProviderState:
        if self.state(ctx).status != ProviderStatus.CONNECTED:
            return self.state(ctx)
        try:
            async with self._client(ctx) as client:
                await self._get(client, ctx, "/tweets/search/recent", {"query": "business", "max_results": 10})
            return ProviderState(ProviderStatus.CONNECTED, "Recent search is available.")
        except RateLimited as exc:
            return ProviderState(ProviderStatus.RATE_LIMITED, str(exc))
        except ProviderError as exc:
            status = ProviderStatus.REQUIRES_PERMISSION if exc.status_code in (402, 403) else ProviderStatus.ERROR
            return ProviderState(status, str(exc))
        except httpx.HTTPError as exc:
            return ProviderState(ProviderStatus.ERROR, str(exc))


def _expanded_user_url(user: dict) -> str | None:
    urls = (((user.get("entities") or {}).get("url") or {}).get("urls")) or []
    for u in urls:
        if u.get("expanded_url"):
            return u["expanded_url"]
    return None


class FacebookProvider:
    info = ProviderInfo(
        key="facebook",
        name="Facebook (manual pages)",
        kind="discovery",
        description=(
            "Meta offers no public business-search API for third parties. Programmatic discovery is "
            "unavailable; paste page URLs plus the business website to analyse them."
        ),
        requires=["manual_urls"],
        docs_url="https://developers.facebook.com/docs/graph-api",
    )

    def state(self, ctx: ProviderContext) -> ProviderState:
        return ProviderState(
            ProviderStatus.UNSUPPORTED,
            "Automated Facebook discovery is not available through authorized APIs. Manual page URLs only.",
        )

    async def search_businesses(self, query: SearchQuery, ctx: ProviderContext) -> list[BusinessCandidate]:
        """Turn manually supplied URLs into candidates. Entries may be `website` or `website|facebook_url`."""
        out: list[BusinessCandidate] = []
        for entry in query.manual_urls:
            parts = [p.strip() for p in entry.split("|") if p.strip()]
            site = next((p for p in parts if business_domain(p)), None)
            page = next((p for p in parts if "facebook.com" in p), None)
            if not site:
                continue  # without a business website there is nothing we may analyse
            domain = business_domain(site)
            out.append(
                BusinessCandidate(
                    name=domain or site,
                    website_url=homepage_url(site),
                    industry=query.industry,
                    country=query.country,
                    city=query.city,
                    source_provider=self.info.key,
                    source_url=page or site,
                    raw={"manual": True, "facebook_page": page},
                )
            )
        return out

    async def test_connection(self, ctx: ProviderContext) -> ProviderState:
        return self.state(ctx)


class ManualProvider(FacebookProvider):
    info = ProviderInfo(
        key="manual",
        name="Manual URLs",
        kind="discovery",
        description="Research a list of company websites you provide.",
        requires=[],
    )

    def state(self, ctx: ProviderContext) -> ProviderState:
        return ProviderState(ProviderStatus.CONNECTED, "Paste company website URLs in the campaign.")
