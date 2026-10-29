"""OpenStreetMap discovery (free, keyless): Nominatim to resolve the area, Overpass to list mapped businesses.

Data © OpenStreetMap contributors, available under the Open Database License (ODbL).
Usage policies: identify the client in the User-Agent and stay at ~1 request/second.
"""

import asyncio
import logging
import re

import httpx

from app.core.config import get_settings
from app.models.enums import ProviderStatus
from app.research.catalog import OSM_TAGS, city_names
from app.research.enrichment.normalize import homepage_url
from app.research.providers.base import (
    BusinessCandidate,
    ProviderContext,
    ProviderError,
    ProviderInfo,
    ProviderState,
    RateLimited,
    SearchQuery,
)

log = logging.getLogger(__name__)

ATTRIBUTION = "© OpenStreetMap contributors (ODbL)"
# OSM area ids are derived from the element id: relation + 3.6e9, way + 2.4e9.
AREA_OFFSET = {"relation": 3_600_000_000, "way": 2_400_000_000}
SOCIAL_TAGS = {
    "contact:instagram": "https://www.instagram.com/{}",
    "contact:facebook": "https://www.facebook.com/{}",
    "contact:snapchat": "https://www.snapchat.com/add/{}",
    "contact:tiktok": "https://www.tiktok.com/@{}",
    "contact:twitter": "https://x.com/{}",
    "contact:linkedin": "https://www.linkedin.com/company/{}",
}


class OsmProvider:
    info = ProviderInfo(
        key="osm",
        name="OpenStreetMap",
        kind="discovery",
        description="Free open map data: mapped clinics, shops and offices with website/phone when tagged. "
        + ATTRIBUTION,
        requires=[],
        docs_url="https://wiki.openstreetmap.org/wiki/Overpass_API",
    )

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None, pause: float = 1.0) -> None:
        self._transport = transport
        self._pause = pause

    def state(self, ctx: ProviderContext) -> ProviderState:
        return ProviderState(ProviderStatus.CONNECTED, "Free; no API key required.")

    def _client(self) -> httpx.AsyncClient:
        s = get_settings()
        return httpx.AsyncClient(
            timeout=90.0,
            transport=self._transport,
            headers={"User-Agent": _user_agent(s.osm_contact_email)},
        )

    async def _area_filter(
        self, client: httpx.AsyncClient, ctx: ProviderContext, query: SearchQuery
    ) -> tuple[str, str]:
        """(Overpass prelude, spatial filter) for the campaign city, or the whole country when no city is set.

        Cities mapped as an administrative boundary use that area; cities Nominatim only knows as a point
        use a radius around that point (OSM_CITY_RADIUS_KM).
        """
        country = query.country.upper()
        if not query.city:
            return f'area["ISO3166-1"="{country}"][admin_level=2]->.a;', "(area.a)"
        city_en, _ = city_names(country, query.city)
        resp = await client.get(
            f"{get_settings().osm_nominatim_url}/search",
            params={"city": city_en or query.city, "countrycodes": country.lower(), "format": "jsonv2", "limit": 3},
        )
        await ctx.record_usage(self.info.key, "nominatim_search", 1, 0.0, resp.status_code < 400, resp.status_code)
        _raise_for(resp, "Nominatim")
        places = resp.json()
        for place in places:
            offset = AREA_OFFSET.get(place.get("osm_type"))
            if offset:
                return f"area(id:{offset + int(place['osm_id'])})->.a;", "(area.a)"
        for place in places:
            if place.get("lat") and place.get("lon"):  # city known only as a point: search a radius around it
                radius = int(get_settings().osm_city_radius_km * 1000)
                return "", f"(around:{radius},{float(place['lat'])},{float(place['lon'])})"
        raise ProviderError(f"OpenStreetMap could not locate the city '{query.city}' in {country}")

    async def search_businesses(self, query: SearchQuery, ctx: ProviderContext) -> list[BusinessCandidate]:
        tags = OSM_TAGS.get(query.industry)
        if not tags:
            raise ProviderError(
                f"OpenStreetMap has no map category for '{query.industry}' (online-only businesses are not mapped)"
            )
        async with self._client() as client:
            prelude, spatial = await self._area_filter(client, ctx, query)
            await asyncio.sleep(self._pause)
            selectors = "".join(f'nwr["{k}"~"^({v})$"]["name"]{spatial};' for k, v in tags)
            # Fetch more than needed: entries with a website are ranked first below.
            ql = f"[out:json][timeout:60];{prelude}({selectors});out center tags {max(query.limit * 4, 50)};"
            elements = await self._overpass(client, ctx, ql)

        excluded = [k.lower() for k in query.excluded_keywords if k]
        found: dict[str, BusinessCandidate] = {}
        for el in elements:
            cand = _to_candidate(el, query)
            if cand is None or any(x in cand.name.lower() for x in excluded):
                continue
            found.setdefault(cand.identifiers["osm"], cand)
        ranked = sorted(found.values(), key=lambda c: (c.website_url is None, c.phone is None))
        return ranked[: query.limit]

    async def _overpass(self, client: httpx.AsyncClient, ctx: ProviderContext, ql: str) -> list[dict]:
        """Run the query on the first Overpass endpoint that is not overloaded."""
        endpoints = [u.strip() for u in get_settings().osm_overpass_url.split(",") if u.strip()]
        last: ProviderError | None = None
        for url in endpoints:
            try:
                resp = await client.post(url, data={"data": ql})
            except httpx.HTTPError as exc:
                last = ProviderError(f"Overpass unreachable ({url}): {exc}", retryable=True)
                continue
            await ctx.record_usage(self.info.key, "overpass_query", 1, 0.0, resp.status_code < 400, resp.status_code)
            try:
                _raise_for(resp, "Overpass")
            except ProviderError as exc:
                if not exc.retryable:
                    raise
                last = exc
                log.info("overpass endpoint busy, trying next", extra={"url": url, "status": resp.status_code})
                continue
            return resp.json().get("elements", [])
        raise last or ProviderError("No Overpass endpoint configured")

    async def test_connection(self, ctx: ProviderContext) -> ProviderState:
        try:
            async with self._client() as client:
                resp = await client.get(
                    f"{get_settings().osm_nominatim_url}/search",
                    params={"city": "Riyadh", "countrycodes": "sa", "format": "jsonv2", "limit": 1},
                )
                _raise_for(resp, "Nominatim")
            return ProviderState(ProviderStatus.CONNECTED, "OpenStreetMap responded successfully.")
        except RateLimited as exc:
            return ProviderState(ProviderStatus.RATE_LIMITED, str(exc))
        except (ProviderError, httpx.HTTPError) as exc:
            return ProviderState(ProviderStatus.ERROR, str(exc))


def _user_agent(contact: str) -> str:
    base = "AILeadHunter/0.1 (self-hosted B2B research tool"
    return f"{base}; contact: {contact})" if contact and "example." not in contact else f"{base})"


def _raise_for(resp: httpx.Response, service: str) -> None:
    if resp.status_code == 429:
        raise RateLimited(f"{service} rate limit reached", retry_after=float(resp.headers.get("retry-after") or 10))
    if resp.status_code >= 400:
        raise ProviderError(
            f"{service} error {resp.status_code}", retryable=resp.status_code >= 500, status_code=resp.status_code
        )


def _first(value: str | None) -> str | None:
    if not value:
        return None
    return value.split(";")[0].strip() or None


def _social_url(tag: str, value: str) -> str:
    if value.startswith(("http://", "https://")):
        return value
    if "/" in value:  # "instagram.com/handle" without scheme
        return f"https://{value}"
    return SOCIAL_TAGS[tag].format(value.lstrip("@"))


def _to_candidate(el: dict, query: SearchQuery) -> BusinessCandidate | None:
    t = el.get("tags") or {}
    name = (t.get("name") or t.get("name:en") or t.get("name:ar") or "").strip()
    if not name:
        return None
    website = _first(t.get("website") or t.get("contact:website") or t.get("url"))
    if website and not re.match(r"^https?://", website, re.I):
        website = f"https://{website}"
    street = " ".join(filter(None, [t.get("addr:housenumber"), t.get("addr:street")]))
    address = ", ".join(filter(None, [street, t.get("addr:suburb") or t.get("addr:district"), t.get("addr:city")]))
    osm_ref = f"{el.get('type')}/{el.get('id')}"
    center = el.get("center") or {"lat": el.get("lat"), "lon": el.get("lon")}
    return BusinessCandidate(
        name=name[:300],
        website_url=homepage_url(website) if website else None,
        industry=query.industry,
        country=query.country,
        city=t.get("addr:city") or query.city,
        address=address[:500] or None,
        description=t.get("description"),
        phone=_first(t.get("phone") or t.get("contact:phone") or t.get("contact:mobile")),
        email=_first(t.get("email") or t.get("contact:email")),
        source_provider="osm",
        source_url=f"https://www.openstreetmap.org/{osm_ref}",
        source_title=f"{name} on OpenStreetMap",
        identifiers={"osm": osm_ref},
        social_urls=[_social_url(k, v) for k, v in t.items() if k in SOCIAL_TAGS and v],
        raw={
            "osm_id": osm_ref,
            "name_ar": t.get("name:ar"),
            "name_en": t.get("name:en"),
            "category": next(
                (f"{k}={t[k]}" for k in ("amenity", "healthcare", "shop", "office", "leisure", "tourism") if k in t),
                None,
            ),
            "opening_hours": t.get("opening_hours"),
            "lat": center.get("lat"),
            "lon": center.get("lon"),
            "attribution": ATTRIBUTION,
        },
    )
