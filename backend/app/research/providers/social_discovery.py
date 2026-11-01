"""Discover businesses through their own social profiles (Instagram, TikTok, Facebook) - many have no website.

Searches the official Brave Search API with `site:` queries built from the industry's local terms and the place
("صالون تجميل التجمع الخامس site:instagram.com"). Only profile URLs are kept (no posts), and only when the
indexed title/bio mentions one of the search terms. Phone/email visible in the indexed bio are kept as listing
contacts; the profile page itself is read later by social enrichment. No login, no visit during discovery.
"""

import asyncio
import logging
import re
from urllib.parse import urlparse

import httpx

from app.core.config import get_settings
from app.models.enums import ProviderStatus
from app.research import geo
from app.research.catalog import COUNTRIES, country_names, industry_terms, is_arabic, place_names
from app.research.enrichment.contacts import EMAIL_RE, social_profile_url
from app.research.enrichment.normalize import normalize_phone
from app.research.enrichment.social_search import SearchBlocked, SearchHit, _fold, web_search
from app.research.providers.base import (
    BusinessCandidate,
    ProviderContext,
    ProviderError,
    ProviderInfo,
    ProviderState,
    SearchQuery,
)

log = logging.getLogger(__name__)

# Bios often print local numbers without a country code ("01001234567"); validated per country below.
LOCAL_PHONE_RE = re.compile(r"(?<![\d+])(?:\+|00)?\d[\d\s\-]{7,14}\d(?!\d)")
PLATFORM_SITES = {"instagram": "instagram.com", "tiktok": "tiktok.com", "facebook": "facebook.com"}
# Title decorations each platform adds around the account name.
_TITLE_TAIL = re.compile(
    r"\s*(\(@[^)]*\)|[•|·][^•|·]*(Instagram|TikTok|Facebook).*$|-\s*(Home|Facebook|الصفحة الرئيسية).*$"
    r"|\|\s*Facebook.*$|on Instagram.*$|Instagram photos and videos.*$)",
    re.I,
)


_BIDI = re.compile(r"[\u200e\u200f\u202a-\u202e\u2066-\u2069]")


def name_from_title(title: str) -> str:
    name = _TITLE_TAIL.sub("", _BIDI.sub("", title or "")).strip(" -|•·")
    return re.sub(r"\s+", " ", name)[:300]


def _squashed(text: str) -> str:
    return re.sub(r"[\W_]+", "", _fold(text))


def place_filter(country: str, city: str | None, region: str | None):
    """Keep a profile unless it names another market's country/city and not ours (bios rarely say where;
    those are kept and ranked after the ones that name our place)."""
    ours = {w for w in (*place_names(country, city, region), *(country_names(country))) if w}
    ours_sq = {_squashed(w) for w in ours if len(_squashed(w)) >= 3}
    foreign: set[str] = set()
    for code, c in COUNTRIES.items():
        if code == country.upper():
            continue
        foreign.update(_squashed(w) for w in (c["name_en"], c["name_ar"]) if w)
        foreign.update(_squashed(w) for pair in c["cities"] for w in pair if w)
    foreign = {w for w in foreign if len(w) >= 4} - ours_sq

    def check(text: str) -> int | None:
        sq = _squashed(text)
        if any(w in sq for w in ours_sq):
            return 1  # names our place
        if any(w in sq for w in foreign):
            return None  # another market
        return 0

    return check


def _relevant(text: str, terms: list[str]) -> bool:
    folded = _fold(text)
    words = {w for t in terms for w in re.findall(r"\w+", _fold(t)) if len(w) > 3}
    return any(w in folded for w in words) if words else True


def build_social_queries(query: SearchQuery, platforms: list[str], max_queries: int) -> list[tuple[str, str]]:
    terms_en, terms_ar = industry_terms(query.industry)
    place_en, place_ar = place_names(query.country, query.city, query.region)
    kw_ar = [k for k in query.keywords if is_arabic(k)]
    kw_en = [k for k in query.keywords if not is_arabic(k)]
    pairs: list[tuple[str, str]] = []
    langs = ["ar", "en"] if query.language == "ar" else ["en", "ar"]
    for i in range(3):
        for lang in langs:
            terms = (kw_ar + terms_ar) if lang == "ar" else (kw_en + terms_en)
            place = place_ar if lang == "ar" else place_en
            if i < len(terms) and place:
                pairs.extend((f"{terms[i]} {place} site:{PLATFORM_SITES[p]}", p) for p in platforms)
    return list(dict.fromkeys(pairs))[:max_queries]


class SocialDiscoveryProvider:
    info = ProviderInfo(
        key="social_discovery",
        name="Social profiles (Instagram / TikTok / Facebook)",
        kind="discovery",
        description="Businesses found by their own Instagram/TikTok/Facebook accounts, including those without a "
        "website (search through the Brave Search API; no login).",
        requires=["api_key"],
        docs_url="https://api-dashboard.search.brave.com/app/documentation/web-search/get-started",
    )

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None, pause: float = 1.1) -> None:
        self._transport = transport
        self._pause = pause  # Brave's base plans allow about one request per second

    def state(self, ctx: ProviderContext) -> ProviderState:
        if not ctx.credentials.get("api_key"):
            return ProviderState(ProviderStatus.REQUIRES_API_KEY, "Uses the Brave Search key; connect Brave first.")
        return ProviderState(ProviderStatus.CONNECTED)

    async def search_businesses(self, query: SearchQuery, ctx: ProviderContext) -> list[BusinessCandidate]:
        key = ctx.credentials.get("api_key")
        if not key:
            raise ProviderError("Social discovery needs a Brave Search key")
        s = get_settings()
        platforms = [p for p in ctx.settings.get("platforms", list(PLATFORM_SITES)) if p in PLATFORM_SITES]
        pairs = build_social_queries(
            query, platforms, int(ctx.settings.get("max_queries", s.social_discovery_max_queries))
        )
        country = (COUNTRIES.get(query.country.upper()) or {}).get("brave_country", "ALL")
        place = await geo.locate(query.country, query.city, query.region)
        terms_en, terms_ar = industry_terms(query.industry)
        terms = [*terms_en, *terms_ar, *query.keywords]
        excluded = [_fold(k) for k in query.excluded_keywords if k]
        where = place_filter(query.country, query.city, query.region)
        # Brave cannot localise markets without a country code (e.g. Egypt): there, a profile is kept only when
        # its indexed text names our place or country, otherwise other markets' accounts flood the results.
        strict = country == "ALL"
        found: dict[str, BusinessCandidate] = {}
        local: dict[str, int] = {}
        for n, (q, platform) in enumerate(pairs):
            if n:
                await asyncio.sleep(self._pause)
            try:
                hits = await web_search(
                    q, brave_key=key, transport=self._transport, country=country, count=20, place=place
                )
            except SearchBlocked as exc:
                await ctx.record_usage(self.info.key, "web_search", 1, 0.0, False, 429)
                if found:
                    break  # keep what was collected
                raise ProviderError(f"Brave Search refused the request: {exc}", status_code=429) from exc
            except httpx.HTTPError as exc:  # one bad query must not end the source
                log.info("brave query failed", extra={"query": q, "error": str(exc)[:200]})
                continue
            await ctx.record_usage(self.info.key, "web_search", 1, s.cost_brave_per_request, True, 200)
            for hit in hits:
                cand = self._to_candidate(hit, platform, query, terms)
                if cand is None or any(x in _fold(cand.name) for x in excluded):
                    continue
                score = where(f"{hit.title} {hit.snippet} {hit.url}")
                if score is None or (strict and score == 0):
                    continue
                ident = cand.identifiers["social"]
                if ident not in found:
                    found[ident] = cand
                    local[ident] = score
            if sum(local.values()) >= query.limit:
                break
        ranked = sorted(found, key=lambda k: local[k], reverse=True)
        return [found[k] for k in ranked][: query.limit]

    def _to_candidate(
        self, hit: SearchHit, platform: str, query: SearchQuery, terms: list[str]
    ) -> BusinessCandidate | None:
        found, canon = social_profile_url(hit.url)
        if found != platform:
            return None
        # The hit must be the account page itself: a video/post URL belongs to whoever posted it (often a
        # customer's review), and TikTok accounts always live at /@handle.
        hit_path = urlparse(hit.url).path.strip("/").lower()
        if hit_path != urlparse(canon).path.strip("/").lower() or (
            platform == "tiktok" and not hit_path.startswith("@")
        ):
            return None
        name = name_from_title(hit.title)
        if len(name) < 2 or not _relevant(f"{hit.title} {hit.snippet}", terms):
            return None
        phone = next(
            (n for raw in LOCAL_PHONE_RE.findall(hit.snippet) if (n := normalize_phone(raw, query.country))), None
        )
        email = next(iter(EMAIL_RE.findall(hit.snippet)), None)
        return BusinessCandidate(
            name=name,
            industry=query.industry,
            country=query.country,
            city=query.city,
            description=hit.snippet[:1000] or None,
            phone=phone,
            email=email,
            source_provider=self.info.key,
            source_url=canon,
            source_title=hit.title[:500] or None,
            identifiers={"social": canon.lower()},
            social_urls=[canon],
            raw={"platform": platform, "title": hit.title, "snippet": hit.snippet},
        )

    async def test_connection(self, ctx: ProviderContext) -> ProviderState:
        return self.state(ctx)
