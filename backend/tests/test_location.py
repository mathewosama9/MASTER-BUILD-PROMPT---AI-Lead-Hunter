"""Every delivered business is in the campaign's place (geo.py + enrichment/location.py)."""

import uuid

import httpx
from sqlalchemy import select

from app.core.config import get_settings
from app.research import geo
from app.research.enrichment.location import judge_location, map_points, place_names_for
from app.research.enrichment.website import _geo_points
from app.research.providers.registry import get_discovery_provider

# Nominatim's real answer for "Al Ahsa" (2026-11): the Eastern Province first, the governorate second.
AL_AHSA_ROWS = [
    {
        "name": "المنطقة الشرقية",
        "display_name": "المنطقة الشرقية, السعودية",
        "lat": "23.3036077",
        "lon": "50.1258804",
        "addresstype": "state",
        "osm_type": "relation",
        "osm_id": 1,
        "place_rank": 8,
        "namedetails": {"name": "المنطقة الشرقية", "name:en": "Eastern Province"},
    },
    {
        "name": "محافظة الأحساء",
        "display_name": "محافظة الأحساء, المنطقة الشرقية, السعودية",
        "lat": "25.3877578",
        "lon": "49.5626628",
        "addresstype": "province",
        "osm_type": "relation",
        "osm_id": 2,
        "place_rank": 12,
        "namedetails": {"name": "محافظة الأحساء", "name:en": "Al-Ahsa Governorate"},
        # a rough outline around the oasis (lon, lat)
        "geojson": {
            "type": "Polygon",
            "coordinates": [[[49.2, 25.0], [50.0, 25.0], [50.0, 25.8], [49.2, 25.8], [49.2, 25.0]]],
        },
    },
]
HOFUF, MUBARRAZ = (25.383, 49.586), (25.41, 49.59)
DAMMAM, RIYADH, JEDDAH = (26.43, 50.10), (24.71, 46.67), (21.49, 39.19)


def test_the_requested_place_is_chosen_not_the_first_answer():
    assert geo.pick_place(AL_AHSA_ROWS, ["Al Ahsa", "الأحساء"])["osm_id"] == 2
    assert (
        geo.place_key("محافظة الأحساء") == geo.place_key("الأحساء") and geo.place_key("Al-Ahsa Governorate") == "ahsa"
    )
    assert geo.place_key("Alexandria") == "alexandria"  # "Al" is only an article before a space or hyphen


async def test_the_place_comes_with_its_boundary(monkeypatch):
    monkeypatch.setattr(get_settings(), "geo_city_lookup", True)
    geo._memory.clear()
    stored = {}

    async def no_cache(key):
        return stored.get(key)

    async def store(key, found):
        stored[key] = found

    monkeypatch.setattr(geo, "_cached", no_cache)
    monkeypatch.setattr(geo, "_store", store)
    place = await geo.locate(
        "SA", "Al Ahsa", transport=httpx.MockTransport(lambda r: httpx.Response(200, json=AL_AHSA_ROWS))
    )
    assert place.exact and place.kind == "province" and place.osm_id == 2 and place.maps_zoom == 10
    assert place.contains(*HOFUF) and place.contains(*MUBARRAZ)
    assert not place.contains(*DAMMAM) and not place.contains(*RIYADH) and not place.contains(*JEDDAH)


def test_points_without_a_boundary_use_a_radius_and_an_unlocated_place_judges_nothing():
    riyadh = geo.Place("SA", "Riyadh", 24.64, 46.72, "Asia/Riyadh", True, kind="city")
    assert riyadh.contains(24.69, 46.68) and not riyadh.contains(*JEDDAH)
    assert geo.Place("SA", "Nowhere", 24.7, 46.7, "Asia/Riyadh", False).contains(*JEDDAH) is None


def test_the_website_says_where_the_business_is():
    embed = '<iframe src="https://www.google.com/maps/embed?pb=!1m18!1m12!1m3!1d3600.5!2d49.5861234!3d25.3831234!2m3"></iframe>'
    link = '<a href="https://www.google.com/maps/place/Clinic/@21.4858123,39.1925123,17z/data=!3d21.4858123!4d39.1925123">map</a>'
    assert map_points(embed) == [(25.3831234, 49.5861234)]
    assert map_points(link) == [(21.4858123, 39.1925123)]
    ld = (
        '<script type="application/ld+json">{"@type":"Dentist","telephone":"+966135551234",'
        '"geo":{"@type":"GeoCoordinates","latitude":"25.38","longitude":"49.58"}}</script>'
    )
    assert _geo_points(ld) == [(25.38, 49.58)]


def test_written_places_both_languages():
    names = place_names_for("SA", "Al Ahsa", None)
    assert names.says("King Fahd Rd, Al Hofuf, Al-Ahsa 36361") == "inside"
    assert names.says("مجمع عيادات بالأحساء") == "inside"
    assert names.says("Tahlia St, Jeddah 23434") == "outside" and names.says("فرعنا في الرياض") == "outside"
    assert names.says("آخر الخبر عن العيادة") is None  # "الخبر" (Khobar) is also "the news"
    assert names.says("Smile Dental Clinic") is None


def test_coordinates_win_over_what_the_text_says():
    place = geo.Place(
        "SA",
        "Al Ahsa",
        25.39,
        49.56,
        "Asia/Riyadh",
        True,
        polygons=geo._freeze([AL_AHSA_ROWS[1]["geojson"]["coordinates"]]),
    )
    names = place_names_for("SA", "Al Ahsa", None)
    chain = [("Branches in Riyadh, Jeddah and Dammam", "website")]
    assert judge_location(place, names, points=[(*HOFUF, "maps")], texts=chain).status == "inside"
    assert judge_location(place, names, points=[(*RIYADH, "maps")], texts=[("Al Ahsa", "x")]).status == "outside"
    assert judge_location(place, names, texts=chain).status == "outside"
    assert judge_location(place, names, texts=[("Clinic", "x")]).status == "unknown"


# ------------------------------------------------------------------------------------------ in a campaign

RIYADH_BOX = geo._freeze([[[[46.4, 24.4], [47.0, 24.4], [47.0, 25.0], [46.4, 25.0], [46.4, 24.4]]]])[0]
OVERPASS = {
    "elements": [
        {
            "type": "node",
            "id": 11,
            "lat": 24.70,
            "lon": 46.65,
            "tags": {"name": "Inside Dental", "amenity": "dentist", "phone": "+966 11 234 5678"},
        },
        {
            "type": "node",
            "id": 12,
            "lat": 21.49,
            "lon": 39.19,
            "tags": {"name": "Jeddah Dental", "amenity": "dentist", "phone": "+966 12 234 5678"},
        },
        {
            "type": "way",
            "id": 13,
            "tags": {"name": "Site Says Jeddah", "amenity": "dentist", "website": "jeddah-smile.sa"},
        },
        {
            "type": "way",
            "id": 14,
            "tags": {"name": "Nowhere Dental", "amenity": "dentist", "website": "nowhere-dental.sa"},
        },
        {"type": "way", "id": 15, "tags": {"name": "Map On Site", "amenity": "dentist", "website": "map-dental.sa"}},
    ]
}
SITES = {
    "jeddah-smile.sa": '<script type="application/ld+json">{"@type":"Dentist","name":"S","address":"Tahlia St, Jeddah",'
    '"telephone":"+966 12 111 2222"}</script><p>Welcome</p>',
    "nowhere-dental.sa": '<p>Welcome to our clinic. Call <a href="tel:+966500000001">us</a></p>',
    "map-dental.sa": '<p>Call <a href="tel:+966500000002">us</a></p><iframe src="https://www.google.com/maps/embed?'
    'pb=!1m18!2d46.6851234!3d24.7111234!2m3"></iframe>',
}


async def test_only_businesses_proven_in_the_place_are_delivered(client, dispatched, db, monkeypatch):
    from app.core import safe_http
    from app.core.db import get_sessionmaker
    from app.models import Business, CampaignLead, CampaignRun, CreditTransaction
    from app.research.pipeline import execute_campaign

    async def no_dns(self, url):
        return url

    async def riyadh(country, city=None, region=None, transport=None):
        return geo.Place("SA", "Riyadh", 24.7, 46.7, "Asia/Riyadh", True, kind="city", polygons=(RIYADH_BOX,))

    def osm(request: httpx.Request) -> httpx.Response:
        if "nominatim" in request.url.host:
            return httpx.Response(
                200,
                json=[
                    {
                        "osm_type": "relation",
                        "osm_id": 123,
                        "lat": "24.7",
                        "lon": "46.7",
                        "name": "Riyadh",
                        "place_rank": 16,
                    }
                ],
            )
        return httpx.Response(200, json=OVERPASS)

    def site(request: httpx.Request) -> httpx.Response:
        html = SITES.get(request.url.host)
        if html and request.url.path == "/":
            return httpx.Response(200, text=f"<html><body>{html}</body></html>", headers={"content-type": "text/html"})
        return httpx.Response(404)

    monkeypatch.setattr(safe_http.SafeFetcher, "_check", no_dns)
    monkeypatch.setattr("app.research.pipeline.geo.locate", riyadh)
    provider = get_discovery_provider("osm")
    monkeypatch.setattr(provider, "_transport", httpx.MockTransport(osm))
    monkeypatch.setattr(provider, "_pause", 0)
    body = {
        "name": "Riyadh dentists",
        "country": "SA",
        "city": "Riyadh",
        "industry": "dental_clinics",
        "sources": [{"provider_key": "osm"}],
        "settings": {"target_count": 10, "max_companies": 10, "min_score": 0, "ai_analysis": False},
        "start": True,
    }
    r = await client.post("/api/v1/campaigns", json=body)
    assert r.status_code == 201, r.text
    cid = uuid.UUID(r.json()["id"])
    async with get_sessionmaker()() as s:
        run = await s.scalar(select(CampaignRun).where(CampaignRun.campaign_id == cid))
        await execute_campaign(s, cid, run.id, site_transport=httpx.MockTransport(site))

    names = set(
        await db.scalars(
            select(Business.name)
            .join(CampaignLead, CampaignLead.business_id == Business.id)
            .where(CampaignLead.campaign_id == cid)
        )
    )
    # Jeddah's map point is dropped at discovery; the site naming Jeddah and the site with no place at all leave
    # after their websites are read; the site whose embedded map is in Riyadh stays.
    assert names == {"Inside Dental", "Map On Site"}
    gone = await db.scalar(select(Business).where(Business.name == "Nowhere Dental"))
    assert gone.deleted_at is not None  # not left in the workspace's lead list either
    charges = (await db.scalars(select(CreditTransaction).where(CreditTransaction.campaign_id == cid))).all()
    assert len(charges) <= 2  # only delivered leads can be charged
    events = (await db.execute(select(geo_event_type()).where(geo_event_campaign() == cid))).scalars().all()
    assert "location_filtered" in events and "relevance_filtered" in events


def geo_event_type():
    from app.models import JobEvent

    return JobEvent.event_type


def geo_event_campaign():
    from app.models import JobEvent

    return JobEvent.campaign_id
