"""Where a campaign searches *from*: every source behaves like a user inside the target country and city.

- Browser (Google Maps, social pages): the country's timezone and region, the city's coordinates as the browser
  geolocation, and an Accept-Language for that market. The UI language stays English because the page parsers
  read English labels; business names and content come back as published.
- Google Maps: searches are centred on the city (`/@lat,lng,zoom`) with the country's `gl`.
- Brave Search API: the official location headers (X-Loc-*) on every request, which accept any country code,
  including markets the `country` parameter does not cover (Egypt, Oman...).

City coordinates come from OpenStreetMap Nominatim (free) and are cached; when a place cannot be resolved the
country's capital is used, so a search is never left without a location.
"""

import json
import logging
import time
from dataclasses import dataclass

import httpx

from app.core.config import get_settings
from app.research.catalog import city_names

log = logging.getLogger(__name__)

# ISO country -> (IANA timezone, capital latitude, capital longitude)
COUNTRY_GEO: dict[str, tuple[str, float, float]] = {
    "SA": ("Asia/Riyadh", 24.7136, 46.6753),
    "AE": ("Asia/Dubai", 25.2048, 55.2708),
    "EG": ("Africa/Cairo", 30.0444, 31.2357),
    "KW": ("Asia/Kuwait", 29.3759, 47.9774),
    "QA": ("Asia/Qatar", 25.2854, 51.5310),
    "BH": ("Asia/Bahrain", 26.2285, 50.5860),
    "OM": ("Asia/Muscat", 23.5880, 58.3829),
    "JO": ("Asia/Amman", 31.9454, 35.9284),
    "LB": ("Asia/Beirut", 33.8938, 35.5018),
    "IQ": ("Asia/Baghdad", 33.3152, 44.3661),
    "SY": ("Asia/Damascus", 33.5138, 36.2765),
    "YE": ("Asia/Aden", 15.3694, 44.1910),
    "PS": ("Asia/Hebron", 31.9038, 35.2034),
    "MA": ("Africa/Casablanca", 33.5731, -7.5898),
    "DZ": ("Africa/Algiers", 36.7538, 3.0588),
    "TN": ("Africa/Tunis", 36.8065, 10.1815),
    "LY": ("Africa/Tripoli", 32.8872, 13.1913),
    "SD": ("Africa/Khartoum", 15.5007, 32.5599),
    "TR": ("Europe/Istanbul", 41.0082, 28.9784),
}
CACHE_TTL = 90 * 24 * 3600
_memory: dict[str, tuple[float, float]] = {}


@dataclass(frozen=True)
class Place:
    country: str  # ISO 3166-1 alpha-2, upper case
    city: str | None  # as typed by the user (any language)
    lat: float
    lon: float
    timezone: str
    exact: bool  # True when the city/region itself was located, False for the country fallback

    @property
    def browser_locale(self) -> str:
        return f"en-{self.country}"

    @property
    def accept_language(self) -> str:
        cc = self.country
        return f"en-{cc},en;q=0.9,ar-{cc};q=0.8,ar;q=0.7"

    @property
    def maps_zoom(self) -> int:
        return 12 if self.exact else 7

    def brave_headers(self) -> dict[str, str]:
        """Brave's location headers. Header values must be ASCII, so a city typed in Arabic is sent by
        coordinates only (which is what drives local ranking anyway)."""
        headers = {
            "X-Loc-Lat": f"{self.lat:.4f}",
            "X-Loc-Long": f"{self.lon:.4f}",
            "X-Loc-Timezone": self.timezone,
            "X-Loc-Country": self.country,
        }
        city_en = city_names(self.country, self.city)[0] if self.city else None
        if city_en and city_en.isascii():
            headers["X-Loc-City"] = city_en
        return headers


def country_place(country: str | None) -> Place:
    """The country itself (capital as the point), with no network call."""
    cc = (country or "").upper()
    tz, lat, lon = COUNTRY_GEO.get(cc, ("UTC", 0.0, 0.0))
    return Place(cc, None, lat, lon, tz, False)


async def locate(
    country: str, city: str | None = None, region: str | None = None, transport: httpx.AsyncBaseTransport | None = None
) -> Place:
    """The campaign's place: the city (else region/governorate) located through Nominatim, cached; the country's
    capital when it cannot be found or lookups are off."""
    base = country_place(country)
    name = (city or region or "").strip()
    if not name or not get_settings().geo_city_lookup:
        return base
    key = f"{base.country}:{name.casefold()}"
    coords = _memory.get(key) or await _cached(key)
    if coords is None:
        coords = await _nominatim(base.country, city, region, transport)
        if coords is not None:
            _memory[key] = coords
            await _store(key, coords)
    if coords is None:
        return Place(base.country, name, base.lat, base.lon, base.timezone, False)
    return Place(base.country, name, coords[0], coords[1], base.timezone, True)


async def _nominatim(
    country: str, city: str | None, region: str | None, transport: httpx.AsyncBaseTransport | None
) -> tuple[float, float] | None:
    from app.research.providers.osm import _user_agent

    s = get_settings()
    city_en = city_names(country, city)[0] if city else None
    attempts = [p for p in (city_en, city, region) if p]
    try:
        async with httpx.AsyncClient(
            timeout=15.0, transport=transport, headers={"User-Agent": _user_agent(s.osm_contact_email)}
        ) as client:
            for q in dict.fromkeys(attempts):
                resp = await client.get(
                    f"{s.osm_nominatim_url}/search",
                    params={"q": q, "countrycodes": country.lower(), "format": "jsonv2", "limit": 1},
                )
                if resp.status_code >= 400:
                    return None
                rows = resp.json()
                if rows and rows[0].get("lat") and rows[0].get("lon"):
                    return float(rows[0]["lat"]), float(rows[0]["lon"])
    except (httpx.HTTPError, ValueError) as exc:
        log.info("place lookup failed", extra={"country": country, "error": str(exc)[:200]})
    return None


async def _cached(key: str) -> tuple[float, float] | None:
    try:
        from app.core.redis import async_redis

        r = async_redis()
        try:
            raw = await r.get(f"geo:v1:{key}")
        finally:
            await r.aclose()
        if raw:
            lat, lon = json.loads(raw)
            _memory[key] = (lat, lon)
            return lat, lon
    except Exception:  # noqa: BLE001 - the cache is an optimisation only
        return None
    return None


async def _store(key: str, coords: tuple[float, float]) -> None:
    try:
        from app.core.redis import async_redis

        r = async_redis()
        try:
            await r.set(f"geo:v1:{key}", json.dumps(coords), ex=CACHE_TTL)
        finally:
            await r.aclose()
    except Exception:  # noqa: BLE001
        log.debug("place cache write failed", extra={"key": key, "at": time.time()})
