"""Is a business really in the campaign's place?

Evidence, strongest first:
1. Coordinates: the map listing's point (Google Maps, OpenStreetMap), the website's schema.org `geo`, or a Google
   Maps link/embed on its pages, tested against the place's real boundary (geo.Place.contains).
2. Written place names: the listing address, the website's structured address and contact page, the social bio,
   the search snippet and the business name. Naming our city/governorate counts as inside; naming only another
   city or country counts as outside.
3. The written address looked up on the map (geo.geocode_address) when nothing above decides.

Coordinates win over text (a chain's site lists many cities; the branch's own point decides). Landline area
codes are NOT used: one code covers several cities (013 = Dammam, Khobar and Al Ahsa), so they would drop
businesses that are in fact inside.
"""

import re
from dataclasses import dataclass, field
from functools import lru_cache

from app.research.catalog import COUNTRIES, country_names, place_names
from app.research.enrichment.social_search import _fold

# Map coordinates written in Google Maps links and embeds.
_MAP_PATTERNS = (
    re.compile(r"!3d(-?\d{1,2}\.\d{3,})!4d(-?\d{1,3}\.\d{3,})"),  # place links: !3d<lat>!4d<lng>
    re.compile(r"!2d(-?\d{1,3}\.\d{3,})!3d(-?\d{1,2}\.\d{3,})"),  # embeds: !2d<lng>!3d<lat>
    re.compile(r"@(-?\d{1,2}\.\d{3,}),(-?\d{1,3}\.\d{3,})"),
    re.compile(r"[?&](?:q|ll|query|center|destination|daddr)=(-?\d{1,2}\.\d{3,})(?:,|%2C)\s*(-?\d{1,3}\.\d{3,})"),
)
_MAP_URL = re.compile(r"""(?:href|src)\s*=\s*["']([^"']*(?:google\.[a-z.]+/maps|maps\.google\.)[^"']*)["']""", re.I)


def map_points(html: str) -> list[tuple[float, float]]:
    """(lat, lon) of every Google Maps link or embed on a page."""
    out: list[tuple[float, float]] = []
    for url in _MAP_URL.findall(html or ""):
        for k, pattern in enumerate(_MAP_PATTERNS):
            m = pattern.search(url)
            if m:
                a, b = float(m.group(1)), float(m.group(2))
                lat, lon = (b, a) if k == 1 else (a, b)
                if -90 <= lat <= 90 and -180 <= lon <= 180 and (lat, lon) not in out:
                    out.append((lat, lon))
                break
    return out


def _variants(name: str) -> set[str]:
    """Folded spellings of a place name, with and without the article ("الأحساء"/"احساء", "Al Ahsa"/"Ahsa")."""
    f = re.sub(r"\s+", " ", _fold(name)).strip()
    out = {f}
    for pre in ("al ", "al-", "el ", "el-", "ال"):
        if f.startswith(pre) and len(f) - len(pre) >= 3:
            out.add(f[len(pre) :])
    return {v for v in out if len(v) >= 3}


def _pattern(names: set[str]) -> re.Pattern[str] | None:
    """Whole-word match of any name; Arabic words may carry a joined prefix (بالأحساء, والرياض)."""
    spellings = {v for n in names for v in _variants(n)}
    parts = sorted(
        {re.escape(v).replace(" ", r"[\s\-]*").replace(r"\-", r"[\s\-]*") for v in spellings}, key=len, reverse=True
    )
    if not parts:
        return None
    return re.compile(rf"(?<!\w)(?:[وبلف](?:ال)?|ال)?(?:{'|'.join(parts)})(?!\w)")


# City names that are also everyday words ("الخبر" = the news, "العين" = the eye): never read as another place.
AMBIGUOUS = {_fold(w) for w in ("الخبر", "العين")}


@dataclass
class PlaceNames:
    ours: re.Pattern[str] | None
    foreign: re.Pattern[str] | None

    def says(self, text: str) -> str | None:
        """ "inside" when the text names our place, "outside" when it names only other places, else None."""
        t = _fold(text or "")
        if not t.strip():
            return None
        if self.ours is not None and self.ours.search(t):
            return "inside"
        if self.foreign is not None and self.foreign.search(t):
            return "outside"
        return None


@lru_cache(maxsize=256)
def place_names_for(country: str, city: str | None, region: str | None) -> PlaceNames:
    """Our place's names (city and region, both languages) and every other catalog city and country."""
    country = country.upper()
    ours = {n for n in (city, region, *place_names(country, city, region)) if n}
    if not city and not region:
        ours |= set(country_names(country))
    our_keys = {v for n in ours for v in _variants(n)}
    foreign: set[str] = set()
    for code, c in COUNTRIES.items():
        for pair in c["cities"]:
            foreign.update(n for n in pair if n)
        if code != country:
            foreign.update(n for n in (c["name_en"], c["name_ar"]) if n)
    foreign = {n for n in foreign if not (_variants(n) & our_keys) and _fold(n) not in AMBIGUOUS}
    return PlaceNames(_pattern(ours), _pattern(foreign))


@dataclass
class LocationVerdict:
    status: str  # inside | outside | unknown
    evidence: list[str] = field(default_factory=list)


def judge_location(
    place,
    names: PlaceNames,
    *,
    points: list[tuple[float, float, str]] = (),
    texts: list[tuple[str, str]] = (),
) -> LocationVerdict:
    """Decide from coordinates first, then written place names. `points` are (lat, lon, where-from); `texts`
    are (text, where-from). `place` is the campaign's geo.Place (points are only judged when it was located)."""
    seen = [(where, place.contains(lat, lon)) for lat, lon, where in points if place is not None]
    ins = [w for w, r in seen if r is True]
    outs = [w for w, r in seen if r is False]
    if ins:
        return LocationVerdict("inside", [f"map point inside ({w})" for w in ins])
    if outs:
        return LocationVerdict("outside", [f"map point outside ({w})" for w in outs])
    said = [(names.says(text), where) for text, where in texts if text]
    if any(s == "inside" for s, _ in said):
        return LocationVerdict("inside", [f"names the place ({w})" for s, w in said if s == "inside"])
    if any(s == "outside" for s, _ in said):
        return LocationVerdict("outside", [f"names another place ({w})" for s, w in said if s == "outside"])
    return LocationVerdict("unknown")
