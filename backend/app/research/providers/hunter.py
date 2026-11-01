"""Hunter.io adapter: Discover (discovery), Domain Search, Company Enrichment and Email Verification.

Only generic/role-based emails are kept unless the workspace explicitly allows named business contacts.
"""

import httpx

from app.core.config import get_settings
from app.models.enums import ProviderStatus
from app.research.enrichment.normalize import business_domain
from app.research.providers.base import (
    BusinessCandidate,
    ProviderContext,
    ProviderError,
    ProviderInfo,
    ProviderState,
    RateLimited,
    SearchQuery,
)

API = "https://api.hunter.io/v2"


class HunterClient:
    def __init__(self, ctx: ProviderContext, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.ctx = ctx
        self._client = httpx.AsyncClient(timeout=20.0, transport=transport)

    async def __aenter__(self) -> "HunterClient":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self._client.aclose()

    async def _call(self, method: str, path: str, operation: str, **kwargs: object) -> dict:
        params = dict(kwargs.pop("params", {}) or {})  # type: ignore[arg-type]
        params["api_key"] = self.ctx.credentials.get("api_key", "")
        resp = await self._client.request(method, f"{API}{path}", params=params, **kwargs)  # type: ignore[arg-type]
        cost = get_settings().cost_hunter_per_request
        ok = resp.status_code < 400
        await self.ctx.record_usage("hunter", operation, 1, cost if ok else 0.0, ok, resp.status_code)
        if resp.status_code == 429:
            raise RateLimited("Hunter rate limit reached")
        if resp.status_code in (401, 403):
            raise ProviderError(
                "Hunter rejected the API key or the plan lacks this endpoint", status_code=resp.status_code
            )
        if resp.status_code == 451:
            raise ProviderError("Hunter declined to process this request (legal restriction)", status_code=451)
        if not ok:
            raise ProviderError(
                f"Hunter error {resp.status_code}", retryable=resp.status_code >= 500, status_code=resp.status_code
            )
        return resp.json()

    async def account(self) -> dict:
        return await self._call("GET", "/account", "account")

    async def discover(self, query: SearchQuery) -> list[dict]:
        location: dict = {"country": query.country.upper()}
        if query.city:
            location["city"] = query.city
        body = {
            "query": " ".join([query.industry.replace("_", " "), *query.keywords[:3]]),
            "headquarters_location": {"include": [location]},
            "limit": min(query.limit, 100),
        }
        data = await self._call("POST", "/discover", "discover", json=body)
        return data.get("data") or []

    async def domain_search(self, domain: str, *, include_personal: bool = False) -> dict:
        params = {"domain": domain, "limit": 10}
        if not include_personal:
            params["type"] = "generic"
        data = await self._call("GET", "/domain-search", "domain_search", params=params)
        return data.get("data") or {}

    async def email_finder(self, domain: str, first_name: str, last_name: str) -> dict:
        """The address Hunter has seen published for this person at this domain (with its sources), if any."""
        params = {"domain": domain, "first_name": first_name, "last_name": last_name}
        data = await self._call("GET", "/email-finder", "email_finder", params=params)
        return data.get("data") or {}

    async def company(self, domain: str) -> dict:
        data = await self._call("GET", "/companies/find", "company_enrichment", params={"domain": domain})
        return data.get("data") or {}

    async def verify(self, email: str) -> dict:
        data = await self._call("GET", "/email-verifier", "email_verifier", params={"email": email})
        return data.get("data") or {}


class HunterDiscoverProvider:
    info = ProviderInfo(
        key="hunter",
        name="Hunter Discover",
        kind="discovery",
        description="Licensed B2B company discovery, domain search and email verification via Hunter.io.",
        requires=["api_key"],
        docs_url="https://hunter.io/api-documentation/v2",
    )

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport

    def state(self, ctx: ProviderContext) -> ProviderState:
        if not ctx.credentials.get("api_key"):
            return ProviderState(ProviderStatus.REQUIRES_API_KEY, "Set HUNTER_API_KEY or add a key in Settings.")
        return ProviderState(ProviderStatus.CONNECTED)

    async def search_businesses(self, query: SearchQuery, ctx: ProviderContext) -> list[BusinessCandidate]:
        if self.state(ctx).status != ProviderStatus.CONNECTED:
            raise ProviderError("Hunter is not configured")
        async with HunterClient(ctx, self._transport) as client:
            rows = await client.discover(query)
        out: list[BusinessCandidate] = []
        for row in rows:
            domain = business_domain(row.get("domain"))
            if not domain:
                continue
            out.append(
                BusinessCandidate(
                    name=(row.get("organization") or domain)[:300],
                    website_url=f"https://{domain}",
                    industry=query.industry,
                    country=query.country,
                    city=query.city,
                    source_provider=self.info.key,
                    source_url=f"https://hunter.io/discover?domain={domain}",
                    raw={k: row.get(k) for k in ("domain", "organization", "emails_count")},
                )
            )
        return out[: query.limit]

    async def test_connection(self, ctx: ProviderContext) -> ProviderState:
        if self.state(ctx).status != ProviderStatus.CONNECTED:
            return self.state(ctx)
        try:
            async with HunterClient(ctx, self._transport) as client:
                acct = await client.account()
            plan = (acct.get("data") or {}).get("plan_name")
            return ProviderState(ProviderStatus.CONNECTED, f"Hunter plan: {plan or 'unknown'}")
        except RateLimited as exc:
            return ProviderState(ProviderStatus.RATE_LIMITED, str(exc))
        except (ProviderError, httpx.HTTPError) as exc:
            return ProviderState(ProviderStatus.ERROR, str(exc))
