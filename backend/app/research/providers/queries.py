"""Search query expansion: industry terms x place x keywords, in Arabic and English, for any market."""

from app.research.catalog import industry_terms, is_arabic, place_names
from app.research.providers.base import SearchQuery


def build_search_queries(q: SearchQuery, max_queries: int = 16) -> list[str]:
    """Most specific first: every local term for the place, then keyword combinations and keyword-only searches,
    in the campaign language first. Places outside the catalog (any governorate or district) are used as typed."""
    terms_en, terms_ar = industry_terms(q.industry)
    place_en, place_ar = place_names(q.country, q.city, q.region)
    keywords_en = [k for k in q.keywords if not is_arabic(k)]
    keywords_ar = [k for k in q.keywords if is_arabic(k)]
    excluded = " ".join(f"-{_quote(k)}" for k in q.excluded_keywords[:5])

    by_lang: dict[str, list[str]] = {"en": [], "ar": []}
    for term in terms_en:
        by_lang["en"].append(f"{term} in {place_en}")
    for term in terms_ar:
        by_lang["ar"].append(f"{term} في {place_ar}")
    for term in terms_en[:3]:
        by_lang["en"].extend(f"{term} {kw} {place_en}" for kw in keywords_en[:3])
    for term in terms_ar[:3]:
        by_lang["ar"].extend(f"{term} {kw} {place_ar}" for kw in keywords_ar[:3])
    by_lang["en"].extend(f"{kw} {place_en}" for kw in keywords_en[:3])
    by_lang["ar"].extend(f"{kw} {place_ar}" for kw in keywords_ar[:3])
    if not terms_en and not terms_ar:
        lang = "ar" if is_arabic(q.industry) else "en"
        by_lang[lang].append(f"{q.industry} {place_ar if lang == 'ar' else place_en}")

    # Interleave the two languages so a small budget still covers both, campaign language first.
    langs = ["ar", "en"] if q.language == "ar" else ["en", "ar"]
    a, b = by_lang[langs[0]], by_lang[langs[1]]
    queries = [x for pair in zip(a, b, strict=False) for x in pair] + a[len(b) :] + b[len(a) :]
    seen: set[str] = set()
    out: list[str] = []
    for query in queries:
        full = f"{query} {excluded}".strip()
        if full.casefold() not in seen:
            seen.add(full.casefold())
            out.append(full)
    return out[:max_queries]


def _quote(k: str) -> str:
    return f'"{k}"' if " " in k else k
