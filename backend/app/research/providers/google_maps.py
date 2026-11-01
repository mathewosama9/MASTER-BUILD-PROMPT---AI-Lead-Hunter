"""Google Maps discovery by direct browser scraping (opt-in: SCRAPING_ENABLED=true).

Opens the public Maps search page, scrolls the result list, then opens each place for its details.
Limits: no login, no captcha solving, no proxy rotation. A challenge page stops the source; places already
collected are kept.
"""

import logging
from collections.abc import Callable
from urllib.parse import quote_plus

from app.core.config import get_settings
from app.models.enums import ProviderStatus
from app.research import geo
from app.research.enrichment.normalize import homepage_url
from app.research.providers.base import (
    BusinessCandidate,
    ProviderContext,
    ProviderError,
    ProviderInfo,
    ProviderState,
    SearchQuery,
)
from app.research.providers.queries import build_search_queries
from app.research.scraping.browser import BrowserSession, BrowserUnavailable, PageSource
from app.research.scraping.parsers import MapsPlace, ScrapeBlocked, maps_feature_id, maps_place_links, parse_maps_place
from app.research.scraping.selectors import MAPS

log = logging.getLogger(__name__)

MAPS_SEARCH = "https://www.google.com/maps/search/{q}?hl=en&gl={gl}"
# Centred on the campaign city, so results are what someone standing there sees.
MAPS_SEARCH_AT = "https://www.google.com/maps/search/{q}/@{lat:.5f},{lon:.5f},{zoom}z?hl=en&gl={gl}"
END_OF_LIST = "reached the end of the list"


def maps_search_url(q: str, country: str, place: geo.Place | None) -> str:
    if place is None or not (place.lat or place.lon):
        return MAPS_SEARCH.format(q=quote_plus(q), gl=country.lower())
    return MAPS_SEARCH_AT.format(
        q=quote_plus(q), lat=place.lat, lon=place.lon, zoom=place.maps_zoom, gl=country.lower()
    )


class GoogleMapsProvider:
    info = ProviderInfo(
        key="google_maps",
        name="Google Maps (direct)",
        kind="discovery",
        description="Businesses from public Google Maps listings via a headless browser: rating, reviews, "
        "category, phone, website. No API key; enable with SCRAPING_ENABLED.",
        requires=[],
        docs_url=None,
    )

    def __init__(self, session_factory: Callable[[str], PageSource] | None = None) -> None:
        self._factory = session_factory

    def state(self, ctx: ProviderContext) -> ProviderState:
        if not get_settings().scraping_enabled:
            return ProviderState(ProviderStatus.DISABLED, "Direct scraping is off. Set SCRAPING_ENABLED=true.")
        return ProviderState(ProviderStatus.CONNECTED, "Direct scraping enabled (no API key).")

    async def search_businesses(self, query: SearchQuery, ctx: ProviderContext) -> list[BusinessCandidate]:
        if self.state(ctx).status != ProviderStatus.CONNECTED:
            raise ProviderError("Google Maps scraping is disabled")
        limit = min(query.limit, get_settings().scraper_max_places_per_campaign)
        place = await geo.locate(query.country, query.city, query.region)
        session = self._factory(query.country) if self._factory else BrowserSession(query.country, place=place)
        found: list[BusinessCandidate] = []
        try:
            links = await self._collect_links(session, ctx, query, limit, place)
            for link in links[:limit]:
                final_url, html = await session.open(link, wait_for=MAPS["name"][0])
                await ctx.record_usage(self.info.key, "place", 1, 0.0, True, 200)
                place = parse_maps_place(html, final_url)
                place.feature_id = place.feature_id or maps_feature_id(link)
                cand = _to_candidate(place, link, query)
                if cand is not None:
                    found.append(cand)
        except ScrapeBlocked as exc:
            await ctx.record_usage(self.info.key, "blocked", 1, 0.0, False, 429)
            if not found:
                raise ProviderError(f"Google Maps blocked automated access: {exc}") from exc
            log.warning("google maps stopped early", extra={"kept": len(found), "reason": str(exc)})
        except BrowserUnavailable as exc:
            raise ProviderError(str(exc)) from exc
        finally:
            await session.close()
        return found

    async def _collect_links(
        self, session: PageSource, ctx: ProviderContext, query: SearchQuery, limit: int, place: geo.Place
    ) -> list[str]:
        links: list[str] = []
        seen: set[str] = set()
        for q in build_search_queries(query, max_queries=int(ctx.settings.get("max_queries", 3))):
            url = maps_search_url(q, query.country, place)
            final_url, html = await session.open(url, wait_for=MAPS["feed"])
            await ctx.record_usage(self.info.key, "search", 1, 0.0, True, 200)
            if "/maps/place/" in final_url:  # a single exact match opens the place directly
                batch = [final_url]
            else:
                html = await session.scroll_feed(MAPS["feed"], max_rounds=max(2, limit // 6), stop_text=END_OF_LIST)
                batch = maps_place_links(html)
            for link in batch:
                key = maps_feature_id(link) or link.split("?")[0]
                if key not in seen:
                    seen.add(key)
                    links.append(link)
            if len(links) >= limit:
                break
        return links

    async def test_connection(self, ctx: ProviderContext) -> ProviderState:
        state = self.state(ctx)
        if state.status != ProviderStatus.CONNECTED:
            return state
        session = self._factory("SA")
        try:
            _, html = await session.open(MAPS_SEARCH.format(q="dentist+Riyadh", gl="sa"), wait_for=MAPS["feed"])
            n = len(maps_place_links(html))
            return ProviderState(ProviderStatus.CONNECTED, f"Google Maps reachable ({n} results on a test search).")
        except ScrapeBlocked as exc:
            return ProviderState(ProviderStatus.RATE_LIMITED, str(exc))
        except BrowserUnavailable as exc:
            return ProviderState(ProviderStatus.ERROR, str(exc))
        except Exception as exc:  # noqa: BLE001 - surface any browser/navigation error to the UI
            return ProviderState(ProviderStatus.ERROR, f"{type(exc).__name__}: {exc}"[:300])
        finally:
            await session.close()


def _to_candidate(place: MapsPlace, link: str, query: SearchQuery) -> BusinessCandidate | None:
    if not place.name:
        return None
    website = place.website if place.website and place.website.startswith("http") else None
    source_url = link.split("?")[0] if "/maps/place/" in link else place.url
    social = []
    if website and any(h in website for h in ("instagram.com", "facebook.com", "snapchat.com", "tiktok.com")):
        social, website = [website], None  # many shops list a social profile as their "website"
    return BusinessCandidate(
        name=place.name[:300],
        website_url=homepage_url(website) if website else None,
        industry=query.industry,
        country=query.country,
        city=query.city,
        address=place.address,
        phone=place.phone,
        description=place.category,
        source_provider="google_maps",
        source_url=source_url[:1000],
        source_title=f"{place.name} on Google Maps",
        identifiers={"gmaps": place.feature_id} if place.feature_id else {},
        social_urls=social,
        raw={
            "category": place.category,
            "rating": place.rating,
            "reviews": place.reviews,
            "hours": place.hours,
            "plus_code": place.plus_code,
            "lat": place.lat,
            "lng": place.lng,
            "feature_id": place.feature_id,
        },
    )
