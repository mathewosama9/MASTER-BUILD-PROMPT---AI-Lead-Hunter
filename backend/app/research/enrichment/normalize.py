"""Normalization helpers shared by discovery, deduplication and contact extraction."""

import re
import unicodedata
from urllib.parse import urlparse

import phonenumbers
import tldextract

# Use the bundled public-suffix snapshot; never fetch at runtime.
_extract = tldextract.TLDExtract(suffix_list_urls=())

# Domains that host many unrelated businesses. A listing on one of these is not the business's own site,
# so the domain must never be used as a dedup key.
SHARED_HOST_DOMAINS = {
    "facebook.com",
    "instagram.com",
    "linkedin.com",
    "twitter.com",
    "x.com",
    "tiktok.com",
    "youtube.com",
    "google.com",
    "goo.gl",
    "maps.app.goo.gl",
    "wa.me",
    "whatsapp.com",
    "snapchat.com",
    "t.me",
    "yelp.com",
    "tripadvisor.com",
    "foursquare.com",
    "yellowpages.com",
    "wikipedia.org",
    "blogspot.com",
    "wordpress.com",
    "wixsite.com",
    "linktr.ee",
    "bit.ly",
    "apple.com",
    "booking.com",
    "zomato.com",
    "talabat.com",
    "noon.com",
    "amazon.com",
    "amazon.sa",
    "amazon.ae",
    "bayut.com",
    "propertyfinder.ae",
    "dubizzle.com",
    "haraj.com.sa",
    "olx.com.eg",
    "vezeeta.com",
}

_ARABIC_DIACRITICS = re.compile(r"[ؐ-ًؚ-ٰٟۖ-ۭـ]")
_LEGAL_SUFFIXES = re.compile(
    r"\b(llc|l\.l\.c|ltd|limited|inc|co|company|corp|fze|fzco|fz-llc|est|establishment|group|"
    r"شركة|مؤسسة|ذ\.م\.م|المحدودة|للتجارة)\b",
    re.IGNORECASE,
)


def normalize_domain(url_or_domain: str | None) -> str | None:
    if not url_or_domain:
        return None
    value = url_or_domain.strip().lower()
    if "://" not in value:
        value = "http://" + value
    host = urlparse(value).hostname
    if not host:
        return None
    ext = _extract(host)
    if not ext.domain or not ext.suffix:
        # Unknown/reserved TLDs (e.g. the `.example` demo TLD): fall back to the last two labels.
        labels = [part for part in host.split(".") if part]
        if len(labels) >= 2 and not host.replace(".", "").isdigit():
            return ".".join(labels[-2:])
        return None
    registered = f"{ext.domain}.{ext.suffix}"
    return registered


def is_shared_host(domain: str | None) -> bool:
    return bool(domain) and domain in SHARED_HOST_DOMAINS


def business_domain(url: str | None) -> str | None:
    """Domain usable as a business identity key (excludes social/directory hosts)."""
    d = normalize_domain(url)
    return None if d is None or is_shared_host(d) else d


def normalize_name(name: str) -> str:
    text = unicodedata.normalize("NFKC", name or "").casefold()
    text = _ARABIC_DIACRITICS.sub("", text)
    text = _LEGAL_SUFFIXES.sub(" ", text)
    text = text.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا").replace("ة", "ه").replace("ى", "ي")
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_email(email: str) -> str | None:
    email = (email or "").strip().lower().strip(".")
    if not re.fullmatch(r"[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,24}", email):
        return None
    return email


def normalize_phone(raw: str, country: str | None) -> str | None:
    """Return E.164 if the number parses as valid for the region, else None."""
    try:
        parsed = phonenumbers.parse(raw, (country or "").upper() or None)
    except phonenumbers.NumberParseException:
        return None
    if not phonenumbers.is_valid_number(parsed):
        return None
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)


def canonical_url(url: str) -> str:
    p = urlparse(url.strip())
    scheme = p.scheme.lower() or "https"
    host = (p.hostname or "").lower()
    path = p.path.rstrip("/") or ""
    return f"{scheme}://{host}{path}"


def homepage_url(url: str) -> str:
    p = urlparse(url if "://" in url else "https://" + url)
    return f"{p.scheme or 'https'}://{p.hostname}"
