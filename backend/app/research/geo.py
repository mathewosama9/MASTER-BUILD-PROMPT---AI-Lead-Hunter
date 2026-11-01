"""Where a campaign searches *from*, and which businesses really are there.

- Browser (Google Maps, social pages): the country's timezone and region, the place's coordinates as the browser
  geolocation, and an Accept-Language for that market. The UI language stays English because the page parsers
  read English labels; business names and content come back as published.
- Google Maps: searches are centred on the place (`/@lat,lng,zoom`) with the country's `gl`.
- Brave Search API: the official location headers (X-Loc-*) on every request, which accept any country code,
  including markets the `country` parameter does not cover (Egypt, Oman...).
- Location checks: `Place.contains(lat, lon)` tests a point against the place's real boundary (OSM polygon), or a
  radius around it when OSM only has a point.

Places come from OpenStreetMap Nominatim (free) and are cached. Nominatim's first answer is often a larger area
with a similar name ("Al Ahsa" -> the whole Eastern Province, centred in the desert), so the answer whose own
name matches the request is chosen, most specific first. When a place cannot be resolved the country's capital is
used, so a search is never left without a location (and `exact` is False, so nothing is judged by distance).
"""

import asyncio
import json
import logging
import math
import re
import time
import unicodedata
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
CACHE_VERSION = "v2"  # v1 stored the first Nominatim answer (often the wrong, larger area)
_memory: dict[str, dict] = {}
# Areas (not settlements): zoomed out on the map.
AREA_KINDS = {"state", "province", "region", "county", "district", "municipality", "governorate"}

Polygon = tuple[tuple[tuple[float, float], ...], ...]  # rings of (lon, lat); the first is the outline


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _in_ring(lon: float, lat: float, ring: tuple[tuple[float, float], ...]) -> bool:
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / ((yj - yi) or 1e-12) + xi:
            inside = not inside
        j = i
    return inside


def _in_polygon(lon: float, lat: float, poly: Polygon) -> bool:
    return bool(poly) and _in_ring(lon, lat, poly[0]) and not any(_in_ring(lon, lat, hole) for hole in poly[1:])


@dataclass(frozen=True)
class Place:
    country: str  # ISO 3166-1 alpha-2, upper case
    city: str | None  # as typed by the user (any language)
    lat: float
    lon: float
    timezone: str
    exact: bool  # True when the city/region itself was located, False for the country fallback
    kind: str = "point"  # Nominatim addresstype: city, town, province, state...
    polygons: tuple[Polygon, ...] = ()  # the place's boundary, when OSM maps it as an area
    osm_type: str | None = None
    osm_id: int | None = None

    @property
    def browser_locale(self) -> str:
        return f"en-{self.country}"

    @property
    def accept_language(self) -> str:
        cc = self.country
        return f"en-{cc},en;q=0.9,ar-{cc};q=0.8,ar;q=0.7"

    @property
    def maps_zoom(self) -> int:
        if not self.exact:
            return 7
        return 10 if self.kind in AREA_KINDS else 12

    def contains(self, lat: float, lon: float, radius_km: float | None = None) -> bool | None:
        """Whether a point lies in this place: inside its boundary, or within `radius_km` (default
        CITY_MATCH_RADIUS_KM) of it when OSM has no boundary. None when the place itself was not located."""
        if not self.exact:
            return None
        if self.polygons:
            return any(_in_polygon(lon, lat, poly) for poly in self.polygons)
        r = radius_km if radius_km is not None else get_settings().city_match_radius_km
        return distance_km(self.lat, self.lon, lat, lon) <= r

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
    found = _memory.get(key) or await _cached(key)
    if found is None:
        found = await _nominatim(base.country, city, region, transport)
        if found is not None:
            _memory[key] = found
            await _store(key, found)
    if found is None:
        return Place(base.country, name, base.lat, base.lon, base.timezone, False)
    return Place(
        base.country,
        name,
        float(found["lat"]),
        float(found["lon"]),
        base.timezone,
        True,
        kind=found.get("kind") or "point",
        polygons=_freeze(found.get("polygons") or []),
        osm_type=found.get("osm_type"),
        osm_id=found.get("osm_id"),
    )


# ------------------------------------------------------------------------------------- choosing an answer

_LEADING = re.compile(
    r"^(?:(?:al|el)[\s\-]+|ال|(?:محافظه|مدينه|منطقه|governorate of|city of|province of)[\s\-]+)", re.I
)
_TRAILING = re.compile(r"[\s\-]+(?:governorate|province|region|city|municipality|district|محافظه|مدينه)$", re.I)


def place_key(name: str) -> str:
    """A place name without articles and admin words, folded: "محافظة الأحساء" -> "احساء", "Al-Ahsa" -> "ahsa"."""
    text = unicodedata.normalize("NFKC", name or "").casefold().strip()
    text = re.sub(r"[ً-ٰٟـ]", "", text).translate(str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ة": "ه", "ى": "ي"}))
    for _ in range(3):
        text = _TRAILING.sub("", _LEADING.sub("", text.strip()))
    return re.sub(r"[\W_]+", "", text)


def _names(row: dict) -> set[str]:
    names = {row.get("name") or "", (row.get("display_name") or "").split(",")[0]}
    details = row.get("namedetails") or {}
    names |= {v for k, v in details.items() if k.startswith(("name", "official_name", "alt_name")) and v}
    return {place_key(n) for n in names if n}


def pick_place(rows: list[dict], wanted: list[str]) -> dict | None:
    """The answer that IS the requested place: its own name matches, most specific (highest place_rank) first;
    without a name match, the most specific settlement-level answer rather than simply the first."""
    keys = {k for w in wanted if w and len(k := place_key(w)) >= 2}
    usable = [r for r in rows if r.get("lat") and r.get("lon")]
    named = [r for r in usable if _names(r) & keys]
    pool = named or [r for r in usable if int(r.get("place_rank") or 30) <= 20] or usable
    if not pool:
        return None
    return max(pool, key=lambda r: int(r.get("place_rank") or 0))


def _polygons(geojson: dict | None) -> list:
    """Nominatim GeoJSON -> list of polygons (rings of [lon, lat], rounded); [] for points and lines."""
    if not isinstance(geojson, dict):
        return []
    coords = geojson.get("coordinates") or []
    if geojson.get("type") == "Polygon":
        polys = [coords]
    elif geojson.get("type") == "MultiPolygon":
        polys = coords
    else:
        return []
    return [[[[round(x, 5), round(y, 5)] for x, y in ring] for ring in poly] for poly in polys]


def _freeze(polys: list) -> tuple:
    return tuple(tuple(tuple((float(x), float(y)) for x, y in ring) for ring in poly) for poly in polys)


async def nominatim_rows(client: httpx.AsyncClient, country: str, q: str) -> list[dict]:
    s = get_settings()
    resp = await client.get(
        f"{s.osm_nominatim_url}/search",
        params={
            "q": q,
            "countrycodes": country.lower(),
            "format": "jsonv2",
            "limit": 5,
            "namedetails": 1,
            "polygon_geojson": 1,
            "polygon_threshold": 0.005,
        },
    )
    resp.raise_for_status()
    rows = resp.json()
    return rows if isinstance(rows, list) else []


async def find_place(client: httpx.AsyncClient, country: str, city: str | None, region: str | None) -> dict | None:
    """The chosen Nominatim answer for the city (English name first, then as typed), else the region."""
    city_en = city_names(country, city)[0] if city else None
    for wanted in ([city_en, city], [region]):
        names = [w for w in wanted if w]
        for q in dict.fromkeys(names):
            row = pick_place(await nominatim_rows(client, country, q), names)
            if row is not None:
                return row
    return None


async def _nominatim(
    country: str, city: str | None, region: str | None, transport: httpx.AsyncBaseTransport | None
) -> dict | None:
    from app.research.providers.osm import _user_agent

    s = get_settings()
    try:
        async with httpx.AsyncClient(
            timeout=20.0, transport=transport, headers={"User-Agent": _user_agent(s.osm_contact_email)}
        ) as client:
            row = await find_place(client, country, city, region)
    except (httpx.HTTPError, ValueError) as exc:
        log.info("place lookup failed", extra={"country": country, "error": str(exc)[:200]})
        return None
    if row is None:
        return None
    return {
        "lat": float(row["lat"]),
        "lon": float(row["lon"]),
        "kind": row.get("addresstype") or row.get("type") or "point",
        "osm_type": row.get("osm_type"),
        "osm_id": int(row["osm_id"]) if row.get("osm_id") else None,
        "polygons": _polygons(row.get("geojson")),
    }


async def _cached(key: str) -> dict | None:
    try:
        from app.core.redis import async_redis

        r = async_redis()
        try:
            raw = await r.get(f"geo:{CACHE_VERSION}:{key}")
        finally:
            await r.aclose()
        if raw:
            found = json.loads(raw)
            _memory[key] = found
            return found
    except Exception:  # noqa: BLE001 - the cache is an optimisation only
        return None
    return None


async def _store(key: str, found: dict) -> None:
    try:
        from app.core.redis import async_redis

        r = async_redis()
        try:
            await r.set(f"geo:{CACHE_VERSION}:{key}", json.dumps(found), ex=CACHE_TTL)
        finally:
            await r.aclose()
    except Exception:  # noqa: BLE001
        log.debug("place cache write failed", extra={"key": key, "at": time.time()})


# ---------------------------------------------------------------------------------------- written addresses

_address_lock = asyncio.Lock()
_last_lookup = [0.0]


async def geocode_address(
    country: str, address: str, transport: httpx.AsyncBaseTransport | None = None
) -> tuple[float, float] | None:
    """A written address placed on the map (Nominatim, at most one request per second, cached), so an address
    naming only a district or street ("King Fahd Rd, Al Hofuf") can still be checked against the place."""
    address = re.sub(r"\s+", " ", address or "").strip()[:200]
    if len(address) < 6 or not get_settings().geo_city_lookup:
        return None
    key = f"addr:{country.upper()}:{address.casefold()}"
    found = _memory.get(key) or await _cached(key)
    if found is None:
        from app.research.providers.osm import _user_agent

        s = get_settings()
        found = {"miss": True}
        async with _address_lock:
            wait = 1.1 - (time.monotonic() - _last_lookup[0])
            if wait > 0:
                await asyncio.sleep(wait)
            try:
                async with httpx.AsyncClient(
                    timeout=15.0, transport=transport, headers={"User-Agent": _user_agent(s.osm_contact_email)}
                ) as client:
                    resp = await client.get(
                        f"{s.osm_nominatim_url}/search",
                        params={"q": address, "countrycodes": country.lower(), "format": "jsonv2", "limit": 1},
                    )
                rows = resp.json() if resp.status_code < 400 else []
                if rows and rows[0].get("lat") and rows[0].get("lon") and int(rows[0].get("place_rank") or 0) >= 16:
                    found = {"lat": float(rows[0]["lat"]), "lon": float(rows[0]["lon"])}
            except (httpx.HTTPError, ValueError) as exc:
                log.info("address lookup failed", extra={"error": str(exc)[:200]})
                return None
            finally:
                _last_lookup[0] = time.monotonic()
        _memory[key] = found
        await _store(key, found)
    return None if found.get("miss") else (float(found["lat"]), float(found["lon"]))
