"""Discover businesses listed in local/industry directories (Yellow Pages, Vezeeta, property portals, Fresha...).

1. Find listing pages with the official Brave Search API: `<term> <place> site:<directory>`.
2. Read each listing page once (robots.txt respected, same SafeFetcher as website research, with a pause) and keep
   the business facts the directory publishes as schema.org data: name, phone, email, own website, address,
   social links. Pages without structured data fall back to the page heading plus tel:/mailto: links when the
   page clearly lists a single business.
A directory that blocks or challenges the crawler is skipped for the rest of the run; nothing is evaded.
Directories are data (catalog.DIRECTORIES + DIRECTORY_SITES env), so markets/industries are added without code.
"""

import asyncio
import json
import logging
import re
from urllib.parse import unquote, urljoin, urlparse

import httpx
from selectolax.lexbor import LexborHTMLParser as HTMLParser

from app.core.config import get_settings
from app.core.safe_http import RobotsDisallowed, SafeFetcher, UnsafeURLError
from app.models.enums import ProviderStatus
from app.research import geo
from app.research.catalog import COUNTRIES, INDUSTRIES, directory_sites, industry_terms, place_names
from app.research.enrichment.contacts import EMAIL_RE, find_phones, social_profile_url
from app.research.enrichment.normalize import business_domain, homepage_url, normalize_domain
from app.research.enrichment.social_search import SearchBlocked, _fold, web_search
from app.research.providers.base import (
    BusinessCandidate,
    ProviderContext,
    ProviderError,
    ProviderInfo,
    ProviderState,
    SearchQuery,
)

log = logging.getLogger(__name__)

_SKIP_TYPES = {
    "person",
    "website",
    "webpage",
    "breadcrumblist",
    "imageobject",
    "videoobject",
    "searchaction",
    "itemlist",
    "listitem",
    "sitenavigationelement",
    "article",
    "blogposting",
    "faqpage",
    "question",
    "answer",
    "review",
    "aggregaterating",
    "offer",
    "postaladdress",
    "geocoordinates",
    "openinghoursspecification",
    "rating",
    "searchresultspage",
    "collectionpage",
    "place",
    "country",
    "city",
    "contactpoint",
    "thing",
}
_BLOCK_MARKERS = re.compile(r"captcha|cf-chl|are you a robot|access denied|attention required", re.I)
# Path words of a directory's list pages (many businesses) vs. one business's own listing page.
_LIST_PATH = re.compile(
    r"/(category|categories|search|list|lists|keywords?|tags?|related|map-category|browse)(/|$|-)", re.I
)
_PROFILE_PATH = re.compile(
    r"/(profile|company|companies|business|businesses|listing|listings|place|places|biz|doctor|doctors|clinic|"
    r"agency|agent|agents|broker|developer|restaurant|school|salon|venue|provider|store|shop)s?/[^/?#]+",
    re.I,
)
# Words of a directory's own headings ("Guide to government schools"), never a business name.
_DIRECTORY_WORDS = re.compile(r"\b(directory|guide|listings?|yellow pages)\b|دليل|الصفحات الصفراء", re.I)


def _types(node: dict) -> list[str]:
    t = node.get("@type")
    return [x.lower() for x in (t if isinstance(t, list) else [t]) if isinstance(x, str)]


def business_entities(html: str) -> list[dict]:
    """Every schema.org business entity on the page, including those nested in ItemLists (list pages)."""
    out: list[dict] = []
    for script in HTMLParser(html).css('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.text() or "")
        except ValueError:
            continue
        stack = [data]
        while stack:
            cur = stack.pop()
            if isinstance(cur, list):
                stack.extend(cur)
                continue
            if not isinstance(cur, dict):
                continue
            stack.extend(v for v in cur.values() if isinstance(v, (dict, list)))
            types = _types(cur)
            if types and not set(types) <= _SKIP_TYPES and isinstance(cur.get("name"), str) and cur["name"].strip():
                out.append(cur)
    return out


def _first_str(v: object) -> str | None:
    if isinstance(v, str) and v.strip():
        return v.strip()
    if isinstance(v, list):
        return next((x.strip() for x in v if isinstance(x, str) and x.strip()), None)
    return None


def _address(v: object) -> str | None:
    if isinstance(v, str):
        return v.strip()[:500] or None
    if isinstance(v, dict):
        parts = [v.get(k) for k in ("streetAddress", "addressLocality", "addressRegion")]
        return ", ".join(p.strip() for p in parts if isinstance(p, str) and p.strip())[:500] or None
    return None


def _own_site(urls: list[str], directory: str) -> str | None:
    for url in urls:
        if normalize_domain(url) == directory or not url.startswith("http"):
            continue
        if business_domain(url):
            return homepage_url(url)
    return None


def _links(v: object) -> list[str]:
    return [x for x in (v if isinstance(v, list) else [v]) if isinstance(x, str)]


def profile_links(html: str, page_url: str, site: str, limit: int = 20) -> list[str]:
    """Links from a directory list page to the listed businesses' own pages on the same directory."""
    out: list[str] = []
    for a in HTMLParser(html).css("a[href]"):
        href = urljoin(page_url, (a.attributes.get("href") or "").strip()).split("#")[0].split("?")[0]
        if normalize_domain(href) != site or _LIST_PATH.search(urlparse(href).path):
            continue
        if _PROFILE_PATH.search(urlparse(href).path) and href not in out:
            out.append(href)
            if len(out) >= limit:
                break
    return out


class DirectoryProvider:
    info = ProviderInfo(
        key="directories",
        name="Local directories",
        kind="discovery",
        description="Business listings on local and industry directories (Yellow Pages, Vezeeta, property portals, "
        "Fresha...), found through the Brave Search API and read once each (robots.txt respected).",
        requires=["api_key"],
    )

    def __init__(
        self,
        transport: httpx.AsyncBaseTransport | None = None,
        site_transport: httpx.AsyncBaseTransport | None = None,
        pause: float = 1.0,
    ) -> None:
        self._transport = transport
        self._site_transport = site_transport
        self._pause = pause

    def state(self, ctx: ProviderContext) -> ProviderState:
        if not ctx.credentials.get("api_key"):
            return ProviderState(ProviderStatus.REQUIRES_API_KEY, "Uses the Brave Search key; connect Brave first.")
        return ProviderState(ProviderStatus.CONNECTED)

    def queries(self, query: SearchQuery) -> list[tuple[str, str]]:
        group = INDUSTRIES.get(query.industry, {}).get("group")
        sites = directory_sites(query.country, query.industry, group)
        terms_en, terms_ar = industry_terms(query.industry)
        place_en, place_ar = place_names(query.country, query.city, query.region)
        kw = list(query.keywords[:2])
        terms = [(t, place_ar) for t in (kw + terms_ar)[:2]] + [(t, place_en) for t in (kw + terms_en)[:2]]
        return list(dict.fromkeys((f"{t} {place} site:{site}", site) for site in sites for t, place in terms))

    async def search_businesses(self, query: SearchQuery, ctx: ProviderContext) -> list[BusinessCandidate]:
        key = ctx.credentials.get("api_key")
        if not key:
            raise ProviderError("Directory search needs a Brave Search key")
        s = get_settings()
        pairs = self.queries(query)
        if not pairs:
            raise ProviderError(f"No directory is configured for {query.country} / {query.industry}")
        country = (COUNTRIES.get(query.country.upper()) or {}).get("brave_country", "ALL")
        place = await geo.locate(query.country, query.city, query.region)
        page_budget = int(ctx.settings.get("max_pages", s.directory_pages_per_campaign))
        pages: dict[str, str] = {}  # listing URL -> directory
        for n, (q, site) in enumerate(pairs):
            if len(pages) >= page_budget:
                break
            if n:
                await asyncio.sleep(self._pause)
            try:
                hits = await web_search(
                    q, brave_key=key, transport=self._transport, country=country, count=20, place=place
                )
            except SearchBlocked as exc:
                await ctx.record_usage(self.info.key, "web_search", 1, 0.0, False, 429)
                if pages:
                    break
                raise ProviderError(f"Brave Search refused the request: {exc}", status_code=429) from exc
            except httpx.HTTPError as exc:  # one bad query must not end the source
                log.info("brave query failed", extra={"query": q, "error": str(exc)[:200]})
                continue
            await ctx.record_usage(self.info.key, "web_search", 1, s.cost_brave_per_request, True, 200)
            for hit in hits:
                if normalize_domain(hit.url) == site and urlparse(hit.url).path.strip("/"):
                    pages.setdefault(hit.url.split("#")[0], site)
        return await self._read_listings(pages, query, page_budget)

    async def _read_listings(self, pages: dict[str, str], query: SearchQuery, budget: int) -> list[BusinessCandidate]:
        found: dict[str, BusinessCandidate] = {}
        blocked: set[str] = set()
        excluded = [_fold(k) for k in query.excluded_keywords if k]
        queue = list(pages.items())
        queued = set(pages)
        async with SafeFetcher(transport=self._site_transport, skip_dns_check=self._site_transport is not None) as f:
            i = 0
            while i < len(queue) and i < budget:
                url, site = queue[i]
                i += 1
                if site in blocked:
                    continue
                if i > 1:
                    await asyncio.sleep(self._pause)
                try:
                    page = await f.get(url)
                except RobotsDisallowed:
                    blocked.add(site)
                    log.info("directory disallows crawling", extra={"site": site})
                    continue
                except (UnsafeURLError, httpx.HTTPError) as exc:
                    log.info("directory page skipped", extra={"url": url, "error": str(exc)[:120]})
                    continue
                if page.status_code in (403, 429) or _BLOCK_MARKERS.search(page.text[:5000]):
                    blocked.add(site)  # challenged: stop using this directory for the run
                    continue
                if page.status_code >= 400 or "html" not in page.content_type:
                    continue
                cands = self.parse_listing(page.text, page.url, site, query)
                for cand in cands:
                    if any(x in _fold(cand.name) for x in excluded):
                        continue
                    key = cand.website_url or cand.phone or f"{site}:{_fold(cand.name)}"
                    found.setdefault(key, cand)
                if not cands:
                    # A list page: read the businesses' own listing pages it links to next (same directory only).
                    fresh = [link for link in profile_links(page.text, page.url, site) if link not in queued]
                    queued.update(fresh)
                    queue[i:i] = [(link, site) for link in fresh]
                if len(found) >= query.limit:
                    break
        return drop_directory_lines(list(found.values()))[: query.limit]

    def parse_listing(self, html: str, url: str, site: str, query: SearchQuery) -> list[BusinessCandidate]:
        out: list[BusinessCandidate] = []
        for e in business_entities(html)[:30]:
            if _DIRECTORY_WORDS.search(e["name"]) or normalize_domain(e["name"]) == site:
                continue  # the directory describing itself
            links = [*_links(e.get("url")), *_links(e.get("sameAs"))]
            if any(normalize_domain(u) == site and not urlparse(u).path.strip("/") for u in _links(e.get("url"))):
                continue
            socials = [c for link in links if (c := social_profile_url(link))[0]]
            out.append(
                self._candidate(
                    name=e["name"].strip(),
                    url=url,
                    site=site,
                    query=query,
                    phone=_first_str(e.get("telephone")),
                    email=(_first_str(e.get("email")) or "").removeprefix("mailto:") or None,
                    website=_own_site(links, site),
                    address=_address(e.get("address")),
                    description=_first_str(e.get("description")),
                    socials=[canon for _, canon in socials],
                )
            )
        if out:
            return out
        return self._fallback(html, url, site, query)

    def _fallback(self, html: str, url: str, site: str, query: SearchQuery) -> list[BusinessCandidate]:
        """No structured data: accept a single-business page (one h1) with a phone or email link."""
        if _LIST_PATH.search(urlparse(url).path):
            return []
        tree = HTMLParser(html)
        for node in tree.css("header, footer, nav, script, style, noscript"):
            node.decompose()  # the directory's own hotline and email live in its page chrome
        h1s = [h.text(strip=True) for h in tree.css("h1") if h.text(strip=True)]
        if len(h1s) != 1 or _DIRECTORY_WORDS.search(h1s[0]):
            return []
        phone = email = website = None
        socials: list[str] = []
        for a in tree.css("a[href]"):
            href = (a.attributes.get("href") or "").strip()
            low = href.lower()
            if low.startswith("tel:") and not phone:
                phone = unquote(href[4:])
            elif low.startswith("mailto:") and not email:
                email = unquote(href[7:].split("?")[0])
            elif href.startswith("http"):
                platform, canon = social_profile_url(href)
                if platform:
                    socials.append(canon)
                elif (
                    not website
                    and normalize_domain(href) != site
                    and business_domain(href)
                    and ("website" in a.text(strip=True).lower() or "الموقع" in a.text(strip=True))
                ):
                    website = homepage_url(urljoin(url, href))
        if not phone:
            body = tree.body.text(separator=" ") if tree.body else ""
            phone = next(iter(find_phones(body, query.country)), None)
            email = email or next(iter(EMAIL_RE.findall(body)), None)
        if not (phone or email or website):
            return []
        return [
            self._candidate(
                name=h1s[0][:300],
                url=url,
                site=site,
                query=query,
                phone=phone,
                email=email,
                website=website,
                socials=socials,
            )
        ]

    def _candidate(
        self,
        *,
        name: str,
        url: str,
        site: str,
        query: SearchQuery,
        phone: str | None = None,
        email: str | None = None,
        website: str | None = None,
        address: str | None = None,
        description: str | None = None,
        socials: list[str] | None = None,
    ) -> BusinessCandidate:
        return BusinessCandidate(
            name=re.sub(r"\s+", " ", name)[:300],
            website_url=website,
            industry=query.industry,
            country=query.country,
            city=query.city,
            address=address,
            description=(description or "")[:1000] or None,
            phone=phone,
            email=email,
            source_provider=self.info.key,
            source_url=url,
            source_title=f"{site} listing",
            identifiers={"directory": url},
            social_urls=list(dict.fromkeys(socials or [])),
            raw={"directory": site},
        )

    async def test_connection(self, ctx: ProviderContext) -> ProviderState:
        return self.state(ctx)


def drop_directory_lines(cands: list[BusinessCandidate]) -> list[BusinessCandidate]:
    """A phone or email shown for several different businesses of one directory is the directory's own line
    (hotline, ads desk), not theirs: remove it from all of them."""

    def key(c: BusinessCandidate, value: str) -> tuple[str, str]:
        return normalize_domain(c.source_url) or "", re.sub(r"[^\w@.]", "", value.lower())

    names: dict[tuple[str, str], set[str]] = {}
    for c in cands:
        for value in (c.phone, c.email):
            if value:
                names.setdefault(key(c, value), set()).add(_fold(c.name))
    shared = {k for k, n in names.items() if len(n) >= 2}
    for c in cands:
        if c.phone and key(c, c.phone) in shared:
            c.phone = None
        if c.email and key(c, c.email) in shared:
            c.email = None
    return cands
