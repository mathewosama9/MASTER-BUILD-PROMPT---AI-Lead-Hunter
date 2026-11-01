"""Paid people finders: the decision maker's direct email/phone when the free sources found none.

Run in the order set by PEOPLE_FINDER_ORDER (default Hunter -> Apollo -> Lusha) and stop at the first one that
returns a direct channel. Every call is metered through `ctx.record_usage`, so it counts against the campaign's
budget. Values come only from the provider's response; nothing is constructed.

- Hunter Email Finder: name + domain -> the address Hunter has seen published (email only).
- Apollo: People Match (name + domain -> email, phone, LinkedIn); People Search names who runs a domain.
- Lusha: Person API (name + company -> emails and phones; numbers flagged "do not call" are skipped).
"""

import logging
from dataclasses import dataclass, field

import httpx

from app.core.config import get_settings
from app.research.enrichment.decision_makers import DecisionMaker, clean_name, role_rank
from app.research.enrichment.normalize import normalize_email, normalize_phone
from app.research.providers.base import ProviderContext, ProviderError, RateLimited
from app.research.providers.hunter import HunterClient

log = logging.getLogger(__name__)

APOLLO_API = "https://api.apollo.io/api/v1"
LUSHA_API = "https://api.lusha.com"
FINDERS = ("hunter", "apollo", "lusha")
# Apollo seniorities that make the decision (People Search filter).
APOLLO_SENIORITIES = ["owner", "founder", "c_suite", "partner", "director"]


@dataclass
class Found:
    email: str | None = None
    phone: str | None = None
    linkedin_url: str | None = None
    role: str | None = None
    source_url: str | None = None
    confidence: float = 0.7
    extra: dict = field(default_factory=dict)

    @property
    def useful(self) -> bool:
        return bool(self.email or self.phone)


def split_name(name: str) -> tuple[str, str] | None:
    parts = DecisionMaker(name, "", "", "", "", 0).bare_name.split()
    if len(parts) < 2:
        return None
    return parts[0], parts[-1]


def _raise_for(resp: httpx.Response, provider: str) -> None:
    if resp.status_code == 429:
        raise RateLimited(f"{provider} rate limit reached")
    if resp.status_code in (401, 402, 403):
        raise ProviderError(
            f"{provider} rejected the API key or the plan lacks this endpoint", status_code=resp.status_code
        )
    if resp.status_code >= 400 and resp.status_code != 404:
        raise ProviderError(
            f"{provider} error {resp.status_code}", retryable=resp.status_code >= 500, status_code=resp.status_code
        )


# ----------------------------------------------------------------------------------------------------- Hunter


async def hunter_find(
    ctx: ProviderContext, dm: DecisionMaker, domain: str, transport: httpx.AsyncBaseTransport | None = None
) -> Found | None:
    names = split_name(dm.name)
    if not names or not domain:
        return None
    async with HunterClient(ctx, transport) as hunter:
        data = await hunter.email_finder(domain, *names)
    email = normalize_email(data.get("email") or "")
    if not email:
        return None
    sources = data.get("sources") or []
    score = data.get("score") or 50
    return Found(
        email=email,
        linkedin_url=data.get("linkedin_url"),
        role=data.get("position"),
        source_url=(sources[0].get("uri") if sources else None) or "https://hunter.io",
        confidence=min(score / 100, 0.9),
    )


# ----------------------------------------------------------------------------------------------------- Apollo


class ApolloClient:
    def __init__(self, ctx: ProviderContext, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.ctx = ctx
        self._client = httpx.AsyncClient(
            base_url=APOLLO_API,
            timeout=20.0,
            transport=transport,
            headers={"x-api-key": ctx.credentials.get("api_key", ""), "Cache-Control": "no-cache"},
        )

    async def __aenter__(self) -> "ApolloClient":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self._client.aclose()

    async def _post(self, path: str, operation: str, body: dict) -> dict:
        resp = await self._client.post(path, json=body)
        ok = resp.status_code < 400
        cost = get_settings().cost_apollo_per_request if ok else 0.0
        await self.ctx.record_usage("apollo", operation, 1, cost, ok, resp.status_code)
        _raise_for(resp, "Apollo")
        return resp.json() if ok else {}

    async def match(self, *, domain: str | None, name: str | None = None, person_id: str | None = None) -> dict:
        body: dict = {"reveal_personal_emails": False}
        if person_id:
            body["id"] = person_id
        if name:
            body["name"] = name
        if domain:
            body["domain"] = domain
        data = await self._post("/people/match", "people_match", body)
        return data.get("person") or {}

    async def search(self, domain: str, titles: list[str]) -> list[dict]:
        body = {
            "q_organization_domains_list": [domain],
            "person_seniorities": APOLLO_SENIORITIES,
            "per_page": 5,
        }
        if titles:
            body["person_titles"] = titles[:10]
        data = await self._post("/mixed_people/api_search", "people_search", body)
        return data.get("people") or []


def _apollo_found(person: dict, country: str | None) -> Found:
    phones = [p.get("sanitized_number") or p.get("raw_number") for p in person.get("phone_numbers") or []]
    phone = next((n for p in phones if p and (n := normalize_phone(p, country))), None)
    email = normalize_email(person.get("email") or "") if person.get("email_status") != "unavailable" else None
    url = person.get("linkedin_url")
    return Found(
        email=email,
        phone=phone,
        linkedin_url=url,
        role=person.get("title"),
        source_url=url or "https://www.apollo.io",
        confidence=0.75 if person.get("email_status") == "verified" else 0.6,
    )


async def apollo_find(
    ctx: ProviderContext,
    dm: DecisionMaker,
    domain: str | None,
    country: str | None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> Found | None:
    if not domain:
        return None
    async with ApolloClient(ctx, transport) as apollo:
        person = await apollo.match(domain=domain, name=dm.bare_name)
    return _apollo_found(person, country) if person else None


async def apollo_name_people(
    ctx: ProviderContext,
    domain: str,
    titles: list[str],
    country: str | None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> list[DecisionMaker]:
    """Who runs `domain`, per Apollo: search by seniority/titles, then match the best one for contacts."""
    async with ApolloClient(ctx, transport) as apollo:
        people = await apollo.search(domain, titles)
        ranked = sorted(people, key=lambda p: role_rank(p.get("title")), reverse=True)
        for p in ranked[:1]:
            person = await apollo.match(domain=domain, person_id=p.get("id")) if p.get("id") else {}
            name = clean_name(person.get("name") or " ".join(filter(None, [p.get("first_name"), p.get("last_name")])))
            role = person.get("title") or p.get("title") or ""
            if not name or not role_rank(role):
                continue
            found = _apollo_found(person, country)
            dm = DecisionMaker(name, role, "apollo", found.source_url or "https://www.apollo.io", role, 0.6)
            _apply(dm, found, "apollo")
            return [dm]
    return []


# ------------------------------------------------------------------------------------------------------ Lusha


async def lusha_find(
    ctx: ProviderContext,
    dm: DecisionMaker,
    domain: str | None,
    company: str,
    country: str | None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> Found | None:
    names = split_name(dm.name)
    if not names:
        return None
    params = {"firstName": names[0], "lastName": names[1], "revealEmails": "true", "revealPhones": "true"}
    if domain:
        params["companyDomain"] = domain
    else:
        params["companyName"] = company
    async with httpx.AsyncClient(timeout=20.0, transport=transport) as client:
        resp = await client.get(
            f"{LUSHA_API}/v2/person", params=params, headers={"api_key": ctx.credentials.get("api_key", "")}
        )
    ok = resp.status_code < 400
    await ctx.record_usage(
        "lusha", "person", 1, get_settings().cost_lusha_per_request if ok else 0.0, ok, resp.status_code
    )
    _raise_for(resp, "Lusha")
    if not ok:
        return None
    body = resp.json() or {}
    data = (body.get("contact") or {}).get("data") or body.get("data") or {}
    emails = [e.get("email") for e in data.get("emailAddresses") or [] if isinstance(e, dict)]
    phones = [p.get("number") for p in data.get("phoneNumbers") or [] if isinstance(p, dict) and not p.get("doNotCall")]
    email = next((n for e in emails if e and (n := normalize_email(e))), None)
    phone = next((n for p in phones if p and (n := normalize_phone(p, country))), None)
    title = data.get("jobTitle")
    social = data.get("socialLinks") or {}
    return Found(
        email=email,
        phone=phone,
        linkedin_url=social.get("linkedin") if isinstance(social, dict) else None,
        role=title.get("title") if isinstance(title, dict) else title,
        source_url="https://www.lusha.com",
        confidence=0.7,
    )


# ------------------------------------------------------------------------------------------------- applying


def _apply(dm: DecisionMaker, found: Found, provider: str) -> None:
    dm.set_channel("email", found.email, provider, found.source_url)
    dm.set_channel("phone", found.phone, provider, found.source_url)
    if found.linkedin_url and "linkedin.com/in/" in found.linkedin_url:
        dm.linkedin_url = dm.linkedin_url or found.linkedin_url
        if "linkedin" not in dm.profiles:
            dm.profiles["linkedin"] = found.linkedin_url
            dm.channel_sources["profile:linkedin"] = provider
    if provider not in dm.sources:
        dm.sources.append(provider)
    dm.confidence = min(0.9, max(dm.confidence, found.confidence))


async def find_contact(
    provider: str,
    ctx: ProviderContext,
    dm: DecisionMaker,
    *,
    domain: str | None,
    company: str,
    country: str | None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> bool:
    """Ask one finder for `dm`'s direct contact; True when it returned an email or phone (applied to `dm`)."""
    if provider == "hunter":
        found = await hunter_find(ctx, dm, domain or "", transport)
    elif provider == "apollo":
        found = await apollo_find(ctx, dm, domain, country, transport)
    elif provider == "lusha":
        found = await lusha_find(ctx, dm, domain, company, country, transport)
    else:
        return False
    if found is None or not found.useful:
        return False
    _apply(dm, found, provider)
    return True


def finder_order() -> list[str]:
    return [p.strip() for p in get_settings().people_finder_order.split(",") if p.strip() in FINDERS]
