"""Pure HTML -> data parsers for scraped pages. No browser here, so every parser is unit-testable."""

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from urllib.parse import parse_qs, unquote, urlparse

from selectolax.lexbor import LexborHTMLParser as HTMLParser

from app.research.scraping.selectors import BLOCK_MARKERS, LOGIN_MARKERS, MAPS

FEATURE_ID_RE = re.compile(r"!1s(0x[0-9a-f]+:0x[0-9a-f]+)", re.I)
LATLNG_RE = re.compile(r"!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)")
COUNT_RE = r"([\d][\d.,]*\s*[KkMm]?)"


class ScrapeBlocked(Exception):
    """The site served a block page or challenge (captcha / unusual traffic)."""


def is_blocked(url: str, html: str) -> bool:
    low = html[:200_000].lower()
    return "/sorry/" in url or any(m in low for m in BLOCK_MARKERS)


def is_login_wall(platform: str, url: str, html: str) -> bool:
    markers = LOGIN_MARKERS.get(platform, ())
    head = html[:100_000]
    return any(m in url or m in head for m in markers)


def parse_count(text: str | None) -> int | None:
    """'1,234' -> 1234, '12.5K' -> 12500, '3M' -> 3000000."""
    if not text:
        return None
    t = text.strip().replace(" ", "")
    mult = 1
    if t[-1:] in ("K", "k"):
        mult, t = 1_000, t[:-1]
    elif t[-1:] in ("M", "m"):
        mult, t = 1_000_000, t[:-1]
    if mult > 1:
        t = t.replace(",", ".") if t.count(",") == 1 and "." not in t else t.replace(",", "")
    else:
        t = t.replace(",", "").replace(".", "")
    try:
        return int(float(t) * mult)
    except ValueError:
        return None


def _first(tree: HTMLParser, selectors: list[str]):  # noqa: ANN202 - selectolax node
    for sel in selectors:
        node = tree.css_first(sel)
        if node is not None:
            return node
    return None


# ------------------------------------------------------------------ Google Maps


def maps_place_links(html: str) -> list[str]:
    tree = HTMLParser(html)
    links: list[str] = []
    for a in tree.css(MAPS["result_link"]):
        href = a.attributes.get("href") or ""
        if "/maps/place/" in href and href not in links:
            links.append(href)
    return links


def maps_feature_id(url: str) -> str | None:
    m = FEATURE_ID_RE.search(unquote(url))
    return m.group(1).lower() if m else None


@dataclass
class MapsPlace:
    url: str
    name: str | None = None
    feature_id: str | None = None
    category: str | None = None
    rating: float | None = None
    reviews: int | None = None
    address: str | None = None
    phone: str | None = None
    website: str | None = None
    plus_code: str | None = None
    hours: str | None = None
    lat: float | None = None
    lng: float | None = None
    closed: str | None = None  # "permanent" | "temporary" when the listing says so


def _label(node, prefix: str = "") -> str | None:  # noqa: ANN001
    if node is None:
        return None
    text = (node.attributes.get("aria-label") or node.text(separator=" ", strip=True) or "").strip()
    if prefix and text.lower().startswith(prefix.lower()):
        text = text[len(prefix) :].strip()
    return text or None


def parse_maps_place(html: str, url: str) -> MapsPlace:
    tree = HTMLParser(html)
    place = MapsPlace(url=url, feature_id=maps_feature_id(url))
    name = _first(tree, MAPS["name"])
    place.name = name.text(strip=True) if name is not None else None
    box = _first(tree, MAPS["rating_box"])
    if box is not None:
        labels = [n.attributes.get("aria-label") for n in box.css("[aria-label]")]
        blob = " ".join(filter(None, [box.text(separator=" ", strip=True), *labels]))
        m = re.search(r"(\d(?:[.,]\d)?)\s*(?:stars?)?", blob)
        if m:
            place.rating = float(m.group(1).replace(",", "."))
        m = re.search(COUNT_RE + r"\s*reviews?", blob, re.I) or re.search(r"\(" + COUNT_RE + r"\)", blob)
        if m:
            place.reviews = parse_count(m.group(1))
    place.category = _label(_first(tree, MAPS["category"]))
    place.address = _label(_first(tree, MAPS["address"]), "Address:")
    phone = _first(tree, MAPS["phone"])
    if phone is not None:
        place.phone = (phone.attributes.get("data-item-id") or "").removeprefix("phone:tel:") or _label(phone, "Phone:")
    site = _first(tree, MAPS["website"])
    if site is not None:
        href = site.attributes.get("href") or ""
        if href.startswith("/url?") or "google.com/url?" in href:  # Google redirect wrapper
            href = parse_qs(urlparse(href).query).get("q", [href])[0]
        place.website = href or None
    place.plus_code = _label(_first(tree, MAPS["plus_code"]), "Plus code:")
    hours = _first(tree, MAPS["hours"])
    if hours is not None:
        place.hours = (_label(hours) or "").replace(". Hide open hours for the week", "")[:300] or None
    m = LATLNG_RE.search(url)
    if m:
        place.lat, place.lng = float(m.group(1)), float(m.group(2))
    # The status line sits at the top of the place panel; only that part is read (not "people also search").
    main = tree.css_first('div[role="main"]') or tree.body
    head = (main.text(separator=" ", strip=True) if main is not None else "")[:1500]
    if re.search(r"\bPermanently closed\b", head, re.I):
        place.closed = "permanent"
    elif re.search(r"\bTemporarily closed\b", head, re.I):
        place.closed = "temporary"
    return place


# ------------------------------------------------------------------ public social profiles


@dataclass
class SocialProfile:
    platform: str
    url: str
    accessible: bool = True
    name: str | None = None
    bio: str | None = None
    followers: int | None = None
    following: int | None = None
    posts: int | None = None
    likes: int | None = None
    website: str | None = None
    category: str | None = None
    extra: dict = field(default_factory=dict)

    def summary(self) -> str:
        if self.extra.get("unavailable"):
            return "LinkedIn says this page is unavailable (removed, renamed or an outdated link)."
        if not self.accessible:
            return "Public data not available to logged-out visitors (login wall or browser challenge); not inspected."
        parts = []
        for label, value in (("followers", self.followers), ("posts", self.posts), ("likes", self.likes)):
            if isinstance(value, int):
                parts.append(f"{value:,} {label}")
            elif value is not None:
                parts.append(f"{value} {label}")
        if self.category:
            parts.append(self.category)
        if self.website:
            parts.append(f"website: {self.website}")
        if self.bio:
            parts.append(f"bio: {self.bio[:300]}")
        return " · ".join(parts) or "Profile reachable; no public counters shown."


def _to_int(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return parse_count(str(value))


def _meta(tree: HTMLParser, *names: str) -> str | None:
    for n in names:
        node = tree.css_first(f'meta[property="{n}"]') or tree.css_first(f'meta[name="{n}"]')
        if node is not None and node.attributes.get("content"):
            return node.attributes["content"].strip()
    return None


def _json_script(tree: HTMLParser, selector: str) -> object | None:
    node = tree.css_first(selector)
    if node is None:
        return None
    try:
        return json.loads(node.text() or "")
    except ValueError:
        return None


def _find_dict(obj: object, key: str, accept: Callable[[object], bool] | None = None) -> dict | None:
    """Depth-first search for the first dict containing `key` (whose value passes `accept`, if given)."""
    stack = [obj]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            if key in cur and (accept is None or accept(cur[key])):
                return cur
            stack.extend(cur.values())
        elif isinstance(cur, list):
            stack.extend(cur)
    return None


def parse_social_profile(platform: str, url: str, html: str) -> SocialProfile:
    if is_login_wall(platform, url, html):
        return SocialProfile(platform, url, accessible=False)
    tree = HTMLParser(html)
    p = SocialProfile(platform, url)
    title = _meta(tree, "og:title", "twitter:title")
    desc = _meta(tree, "og:description", "description", "twitter:description")
    p.name = title.split(" (@")[0].split(" • ")[0].split(" | ")[0].strip() if title else None

    if platform == "instagram" and desc:
        # "1,234 Followers, 56 Following, 789 Posts - See Instagram photos and videos from Name (@handle)"
        for attr, word in (("followers", "Followers"), ("following", "Following"), ("posts", "Posts")):
            m = re.search(COUNT_RE + r"\s*" + word, desc, re.I)
            if m:
                setattr(p, attr, parse_count(m.group(1)))
        # The plain meta description carries the bio: '... (@handle) on Instagram: "bio text"'.
        full = _meta(tree, "description") or desc
        m = re.search(r'on Instagram: "(.+)"\s*$', full, re.S)
        p.bio = m.group(1).strip() if m else None
    elif platform == "facebook" and desc:
        # "Name. 12,345 likes · 200 talking about this · 30 were here. Bio text"
        m = re.search(COUNT_RE + r"\s*likes", desc, re.I)
        p.likes = parse_count(m.group(1)) if m else None
        m = re.search(COUNT_RE + r"\s*followers", desc, re.I)
        p.followers = parse_count(m.group(1)) if m else None
        p.bio = re.split(r"(?:were here|talking about this)\.?\s*", desc)[-1].strip() or None
    elif platform == "snapchat":
        data = _json_script(tree, "script#__NEXT_DATA__")
        # Public (business/creator) profiles carry a numeric subscriberCount; the same key also appears in
        # translation templates ("{subscriberCount} Subscribers"), so only digit values count.
        info = _find_dict(data, "subscriberCount", lambda v: str(v).strip().isdigit()) if data else None
        user = _find_dict(data, "displayName") if data else None
        if info:
            p.name = info.get("title") or info.get("displayName") or p.name
            p.bio = info.get("bio") or None
            p.followers = int(str(info["subscriberCount"]).strip())
            p.website = info.get("websiteUrl") or None
            p.category = info.get("categoryStringId") or None
        elif user:
            p.name = user.get("displayName") or p.name
        if not p.bio and desc and not desc.endswith(("is on Snapchat!", ")")):
            p.bio = desc
    elif platform == "tiktok":
        data = _json_script(tree, "script#__UNIVERSAL_DATA_FOR_REHYDRATION__") or _json_script(
            tree, "script#SIGI_STATE"
        )
        stats = _find_dict(data, "followerCount") if data else None
        user = _find_dict(data, "signature") if data else None
        if stats:
            # TikTok sends these as numbers or as strings ("12.5K") depending on the page variant.
            p.followers = _to_int(stats.get("followerCount"))
            p.likes = _to_int(stats.get("heartCount") or stats.get("heart"))
            p.posts = _to_int(stats.get("videoCount"))
        if user:
            p.name = user.get("nickname") or p.name
            p.bio = user.get("signature") or None
            link = (user.get("bioLink") or {}).get("link") if isinstance(user.get("bioLink"), dict) else None
            p.website = link or None
        if not stats and desc:
            p.bio = desc
    elif platform == "linkedin":
        if "/company/unavailable" in url:  # LinkedIn's page for a removed/renamed company or an outdated link
            p.accessible = False
            p.extra["unavailable"] = True
            return p
        # Company header (logged in): "Software Development Redmond, Washington 29M followers 10K+ employees".
        # The body also embeds large JSON blobs in <code>/<script>; drop them so the visible text is searched.
        for node in tree.css("script, style, code, template, noscript"):
            node.decompose()
        text = " ".join(filter(None, [desc, tree.body.text(separator=" ") if tree.body else ""]))
        text = re.sub(r"\s+", " ", text)[:400_000]
        m = re.search(COUNT_RE + r"\s*followers", text, re.I)
        p.followers = parse_count(m.group(1)) if m else None
        m = re.search(r"(\d[\d,.]*[KkMm]?\+?(?:\s*-\s*\d[\d,.]*[KkMm]?\+?)?)\s*employees", text, re.I)
        if m:
            p.extra["employees"] = m.group(1).replace(" ", "")
            p.category = f"{p.extra['employees']} employees"
        p.bio = desc
    else:
        p.bio = desc
    if p.bio:
        p.bio = p.bio[:1000]
    counters = (p.followers, p.following, p.posts, p.likes)
    if all(v is None for v in counters) and not (p.bio or p.website or p.category):
        p.accessible = False  # e.g. LinkedIn's sign-in shell: a page loaded but exposed no profile data
    return p
