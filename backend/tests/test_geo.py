"""Every source searches from inside the campaign's country and city (geo.py)."""

import httpx

from app.core.config import get_settings
from app.research import geo
from app.research.enrichment.social_search import web_search
from app.research.providers.google_maps import maps_search_url
from app.research.scraping.browser import BrowserSession


def test_each_country_has_its_own_timezone_and_point():
    sa, eg, om = geo.country_place("SA"), geo.country_place("eg"), geo.country_place("OM")
    assert (sa.timezone, eg.timezone, om.timezone) == ("Asia/Riyadh", "Africa/Cairo", "Asia/Muscat")
    assert om.browser_locale == "en-OM" and "ar-OM" in om.accept_language
    assert round(om.lat) == 24 and round(om.lon) == 58


def test_brave_location_headers_cover_markets_brave_has_no_country_code_for():
    h = geo.Place("EG", "المنوفية", 30.5, 31.0, "Africa/Cairo", True).brave_headers()
    assert h["X-Loc-Country"] == "EG" and h["X-Loc-Lat"] == "30.5000" and h["X-Loc-Timezone"] == "Africa/Cairo"
    assert "X-Loc-City" not in h  # header values must be ASCII; the coordinates carry the city
    assert geo.Place("OM", "Muscat", 23.6, 58.4, "Asia/Muscat", True).brave_headers()["X-Loc-City"] == "Muscat"


async def test_city_is_located_once_then_cached(monkeypatch):
    monkeypatch.setattr(get_settings(), "geo_city_lookup", True)
    geo._memory.clear()
    stored = {}

    async def no_cache(key):
        return stored.get(key)

    async def store(key, coords):
        stored[key] = coords

    monkeypatch.setattr(geo, "_cached", no_cache)
    monkeypatch.setattr(geo, "_store", store)
    calls = []

    def nominatim(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.params["q"])
        assert request.url.params["countrycodes"] == "om"
        return httpx.Response(200, json=[{"lat": "22.9333", "lon": "57.5333"}])

    place = await geo.locate("OM", "Nizwa", transport=httpx.MockTransport(nominatim))
    again = await geo.locate("OM", "Nizwa", transport=httpx.MockTransport(nominatim))
    assert place.exact and (place.lat, place.lon) == (22.9333, 57.5333) and place.timezone == "Asia/Muscat"
    assert again == place and calls == ["Nizwa"] and list(stored) == ["OM:nizwa"]
    assert (stored["OM:nizwa"]["lat"], stored["OM:nizwa"]["lon"]) == (22.9333, 57.5333)


async def test_unknown_place_falls_back_to_the_country(monkeypatch):
    monkeypatch.setattr(get_settings(), "geo_city_lookup", True)
    geo._memory.clear()

    async def nothing(*_):
        return None

    monkeypatch.setattr(geo, "_cached", nothing)
    monkeypatch.setattr(geo, "_store", nothing)
    place = await geo.locate("SA", "Nowhere-xyz", transport=httpx.MockTransport(lambda r: httpx.Response(200, json=[])))
    assert not place.exact and place.timezone == "Asia/Riyadh" and place.maps_zoom == 7


def test_google_maps_search_is_centred_on_the_city():
    place = geo.Place("OM", "Muscat", 23.588, 58.3829, "Asia/Muscat", True)
    url = maps_search_url("dentist in Muscat", "OM", place)
    assert "/@23.58800,58.38290,12z" in url and url.endswith("gl=om")


def test_browser_runs_as_a_user_in_the_target_country():
    opts = BrowserSession("EG", place=geo.Place("EG", "Cairo", 30.04, 31.23, "Africa/Cairo", True))._context_options()
    assert opts["timezone_id"] == "Africa/Cairo" and opts["locale"] == "en-EG"
    assert opts["geolocation"] == {"latitude": 30.04, "longitude": 31.23} and opts["permissions"] == ["geolocation"]
    assert "ar-EG" in opts["extra_http_headers"]["Accept-Language"]
    assert BrowserSession("SA")._context_options()["timezone_id"] == "Asia/Riyadh"


async def test_every_brave_query_carries_the_place():
    seen = {}

    def brave(request: httpx.Request) -> httpx.Response:
        seen.update(request.headers)
        return httpx.Response(200, json={"web": {"results": []}})

    place = geo.Place("OM", "Muscat", 23.588, 58.3829, "Asia/Muscat", True)
    await web_search("x", brave_key="k", transport=httpx.MockTransport(brave), place=place)
    assert seen["x-loc-country"] == "OM" and seen["x-loc-city"] == "Muscat" and seen["x-loc-lat"] == "23.5880"
