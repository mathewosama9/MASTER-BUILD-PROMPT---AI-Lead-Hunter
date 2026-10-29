"""Search query expansion: industry x city x keywords, in English and Arabic."""

from app.research.catalog import city_names, country_names, industry_terms
from app.research.providers.base import SearchQuery


def build_search_queries(q: SearchQuery, max_queries: int = 8) -> list[str]:
    terms_en, terms_ar = industry_terms(q.industry)
    city_en, city_ar = city_names(q.country, q.city)
    country_en, country_ar = country_names(q.country)
    place_en = city_en or q.region or country_en
    place_ar = city_ar or country_ar

    keywords_en = [k for k in q.keywords if not _is_arabic(k)]
    keywords_ar = [k for k in q.keywords if _is_arabic(k)]
    excluded = " ".join(f"-{_quote(k)}" for k in q.excluded_keywords[:5])

    queries: list[str] = []
    langs = ["ar", "en"] if q.language == "ar" else ["en", "ar"]
    for lang in langs:
        if lang == "en":
            for term in terms_en:
                queries.append(f"{term} in {place_en}")
                for kw in keywords_en[:3]:
                    queries.append(f"{term} {kw} {place_en}")
        elif place_ar:
            for term in terms_ar:
                queries.append(f"{term} في {place_ar}")
                for kw in keywords_ar[:3]:
                    queries.append(f"{term} {kw} {place_ar}")
    if not terms_en and not terms_ar:
        queries.append(f"{q.industry} {place_en}")

    seen: set[str] = set()
    out: list[str] = []
    for query in queries:
        full = f"{query} {excluded}".strip()
        if full.casefold() not in seen:
            seen.add(full.casefold())
            out.append(full)
    return out[:max_queries]


def _is_arabic(text: str) -> bool:
    return any("؀" <= ch <= "ۿ" for ch in text)


def _quote(k: str) -> str:
    return f'"{k}"' if " " in k else k
