"""Public social profile enrichment (Instagram, Facebook pages, Snapchat, TikTok, LinkedIn company pages).

Opens each profile URL the business already published (website, Maps, OSM, import) in the shared headless
browser and reads the counters/bio the page shows to logged-out visitors. A login wall is recorded as
"not accessible", never guessed around. Only business profiles are visited (see `social_profile_url`).
"""

from app.research.enrichment.contacts import EMAIL_RE, PHONE_RE, social_profile_url
from app.research.scraping.browser import PageSource
from app.research.scraping.parsers import SocialProfile, is_login_wall, parse_social_profile
from app.research.scraping.sessions import SessionExpired

SUPPORTED = ("instagram", "facebook", "snapchat", "tiktok", "linkedin")


def platform_of(url: str) -> str | None:
    platform, _ = social_profile_url(url)
    return platform if platform in SUPPORTED else None


async def fetch_profile(source: PageSource, url: str, logged_in: bool = False) -> SocialProfile | None:
    """Open a profile page; with `logged_in`, through the user's linked account for that platform.

    Raises SessionExpired when a logged-in visit lands on a login/checkpoint page.
    """
    platform, canon = social_profile_url(url)
    if platform not in SUPPORTED:
        return None
    final_url, html = await source.open(canon, session=platform if logged_in else None)
    profile = parse_social_profile(platform, final_url, html)
    if logged_in and not profile.accessible and is_login_wall(platform, final_url, html):
        raise SessionExpired(platform)
    if logged_in:
        profile.extra["logged_in"] = True
    return profile


def contacts_in_bio(profile: SocialProfile) -> tuple[list[str], list[str]]:
    """(emails, phones) written in the bio text. Callers normalize and label them with the platform."""
    text = profile.bio or ""
    return list(dict.fromkeys(EMAIL_RE.findall(text))), list(dict.fromkeys(PHONE_RE.findall(text)))
