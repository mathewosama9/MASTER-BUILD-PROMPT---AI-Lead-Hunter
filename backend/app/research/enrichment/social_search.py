"""Find a business's own social profiles by name when it did not publish links to them.

One web search per missing platform (`"<name>" <city> site:instagram.com`). A hit is accepted only when it
clearly belongs to the business: its website domain or phone number appears in the result (strong), or the
result title/handle carries the business's distinctive name tokens (weaker, flagged for manual review).
Search goes through the official Brave Search API only, so it runs when a Brave key is connected.
"""

import re
import unicodedata
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from app.research.enrichment.contacts import social_profile_url

SEARCH_PLATFORMS = {
    "instagram": "instagram.com",
    "facebook": "facebook.com",
    "tiktok": "tiktok.com",
    "snapchat": "snapchat.com",
}
BRAVE_URL = "https://api.search.brave.com/res/v1/web/search"
STRONG_CONFIDENCE = 0.6
NAME_CONFIDENCE = 0.4
NAME_ONLY_NOTE = "Found by searching the business name; confirm this is the business's own account before use."

# Words that describe a kind of business rather than this business, in English and Arabic.
_GENERIC = {
    "the",
    "and",
    "of",
    "for",
    "co",
    "company",
    "llc",
    "ltd",
    "est",
    "group",
    "center",
    "centre",
    "clinic",
    "clinics",
    "medical",
    "dental",
    "store",
    "shop",
    "office",
    "services",
    "institute",
    "academy",
    "school",
    "restaurant",
    "cafe",
    "salon",
    "hotel",
    "agency",
    "trading",
    "branch",
    "official",
    "page",
    "account",
    "شركة",
    "مؤسسة",
    "مركز",
    "عيادة",
    "عيادات",
    "مجمع",
    "طبي",
    "لطب",
    "الأسنان",
    "اسنان",
    "معهد",
    "أكاديمية",
    "اكاديمية",
    "مدرسة",
    "مطعم",
    "مقهى",
    "صالون",
    "فندق",
    "وكالة",
    "للتجارة",
    "فرع",
    "الرسمي",
    "الرسمية",
}


class SearchBlocked(Exception):
    """The search engine refused or challenged the request; stop searching for this run."""


@dataclass
class SearchHit:
    url: str
    title: str
    snippet: str


@dataclass
class ProfileMatch:
    platform: str
    url: str
    confidence: float
    strong: bool
    source_url: str


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "").lower()
    text = re.sub(r"[ً-ٰٟـ]", "", text)  # Arabic diacritics and tatweel
    return text.translate(str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ة": "ه", "ى": "ي"}))


def name_tokens(name: str) -> list[str]:
    tokens = re.findall(r"[\w]+", _fold(name))
    generic = {_fold(g) for g in _GENERIC}
    out = []
    for tok in tokens:
        bare = tok[2:] if tok.startswith("ال") and len(tok) > 4 else tok  # Arabic definite article
        if len(bare) >= 3 and tok not in generic and bare not in generic and not bare.isdigit():
            out.append(bare)
    return list(dict.fromkeys(out))


def _squash(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", _fold(text))


def _digits(text: str) -> str:
    return re.sub(r"\D", "", text or "")


def match_hit(
    hit: SearchHit,
    platform: str,
    business_name: str,
    *,
    domain: str | None = None,
    phones: list[str] | None = None,
) -> ProfileMatch | None:
    """Return a match when `hit` is plausibly `business_name`'s own profile on `platform`."""
    found, canon = social_profile_url(hit.url)
    if found != platform:
        return None
    handle = urlparse(canon).path.strip("/").removeprefix("@").removeprefix("add/")
    text = _fold(f"{hit.title} {hit.snippet}")
    digits = _digits(hit.snippet + " " + hit.title)
    strong = bool(domain and domain.lower() in text) or any(
        len(d := _digits(p)) >= 8 and d[-8:] in digits for p in (phones or [])
    )
    tokens = name_tokens(business_name)
    haystack = f"{text} {_fold(handle)}"
    covered = sum(1 for tok in tokens if tok in haystack) / len(tokens) if tokens else 0.0
    squashed = _squash(business_name)
    handle_hit = len(squashed) >= 5 and (squashed in _squash(handle) or _squash(handle) in squashed)
    if strong and (covered >= 0.5 or handle_hit or not tokens):
        return ProfileMatch(platform, canon, STRONG_CONFIDENCE, True, hit.url)
    # Name-only: one distinctive word ("Smile") is too common, so it must match the whole handle instead.
    if (covered >= 0.75 and len(tokens) >= 2) or handle_hit:
        return ProfileMatch(platform, canon, NAME_CONFIDENCE, False, hit.url)
    return None


def best_match(
    hits: list[SearchHit], platform: str, business_name: str, *, domain: str | None, phones: list[str]
) -> ProfileMatch | None:
    matches = [m for h in hits if (m := match_hit(h, platform, business_name, domain=domain, phones=phones))]
    return max(matches, key=lambda m: m.confidence) if matches else None


def build_query(business_name: str, city: str | None, platform: str) -> str:
    return f'"{business_name.strip()}" {city or ""} site:{SEARCH_PLATFORMS[platform]}'.replace("  ", " ")


async def web_search(
    query: str, *, brave_key: str, transport: httpx.AsyncBaseTransport | None = None
) -> list[SearchHit]:
    """Run one query through the official Brave Search API (the only search backend; it needs a key)."""
    async with httpx.AsyncClient(timeout=15.0, transport=transport) as client:
        resp = await client.get(
            BRAVE_URL,
            params={"q": query, "count": 10, "result_filter": "web"},
            headers={"Accept": "application/json", "X-Subscription-Token": brave_key},
        )
    if resp.status_code in (401, 402, 403, 429):
        raise SearchBlocked(f"Brave Search returned {resp.status_code}")
    resp.raise_for_status()
    results = (resp.json().get("web") or {}).get("results") or []
    return [
        SearchHit(r["url"], r.get("title") or "", re.sub(r"<[^>]+>", "", r.get("description") or ""))
        for r in results
        if r.get("url")
    ]
