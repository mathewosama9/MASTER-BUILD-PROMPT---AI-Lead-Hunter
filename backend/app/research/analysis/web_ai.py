"""AI research council: ask several web-searching models who runs a business.

Each connected model (Perplexity Agent API, Gemini with Grounding with Google Search, OpenAI Responses with web
search) gets the same question with the business's full identity and must name its sources. The answers are only
LEADS: a model can mistake a namesake company or invent a name, so nothing here is delivered as is. Every person
is checked by enrichment/verify_people.py against pages the platform fetches itself.

The three APIs share the Responses shape (a list of output items/steps with text parts, url_citation
annotations and search results), and change often, so the parsing below walks the reply generically instead of
depending on one exact layout. Model ids are settings.
"""

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field

import httpx
from pydantic import BaseModel, Field, ValidationError

from app.core.config import get_settings
from app.research import brave_keys

log = logging.getLogger(__name__)

COUNCIL = ("perplexity", "gemini", "openai")
TIMEOUT = 90.0


@dataclass
class CouncilPerson:
    name: str
    role: str
    quote: str = ""
    urls: list[str] = field(default_factory=list)


@dataclass
class WebAnswer:
    provider: str
    people: list[CouncilPerson] = field(default_factory=list)
    citations: list[str] = field(default_factory=list)  # every source URL the model's search returned
    cost_usd: float = 0.0
    error: str | None = None


class _Person(BaseModel):
    name: str
    role: str = ""
    quote: str = ""
    source_urls: list[str] = Field(default_factory=list)


class _People(BaseModel):
    people: list[_Person] = Field(default_factory=list, max_length=6)


COUNCIL_SYSTEM = """You research who runs a specific local business, using web search.
Rules:
- Find the person or people who make the decisions there TODAY: owner, founder, CEO, managing director, general \
manager, managing partner, medical director, school principal or the local equivalent.
- The business is identified by ALL the details given (name, city, country, website, phone). A person at another \
company with a similar name, in another city or country, or who held the role in the past, does not count.
- Every person must come with the URLs of the pages that state their name together with this business, and a \
short quote copied from one of those pages.
- Prefer the business's own website, official registries, LinkedIn and reputable press. Ignore people who are \
only staff, customers, reviewers or authors writing about the business.
- Copy the name in the script and spelling the source uses (Arabic stays Arabic). Never guess, transliterate into \
a new spelling, or complete a partial name. If you cannot find a well-sourced answer, return an empty list. An \
empty list is a good answer; a wrong person is a bad one.
- At most 3 people, most senior first. role is their title at this business as the source states it.
- Reply with exactly one JSON object and nothing else:
{"people": [{"name": "...", "role": "...", "quote": "...", "source_urls": ["https://..."]}]}"""


def council_prompt(business: dict) -> str:
    lines = [f"{k}: {v}" for k, v in business.items() if v]
    return "Business:\n" + "\n".join(lines) + "\n\nWho runs this business today? Answer in the JSON format only."


# ------------------------------------------------------------------------------------------ reply parsing


def _texts(node: object) -> list[str]:
    """Answer text parts anywhere in a Responses-style reply (output_text / text items)."""
    out: list[str] = []
    if isinstance(node, dict):
        if node.get("type") in ("output_text", "text") and isinstance(node.get("text"), str):
            out.append(node["text"])
        for v in node.values():
            if isinstance(v, (dict, list)):
                out += _texts(v)
    elif isinstance(node, list):
        for v in node:
            out += _texts(v)
    return out


def _urls(node: object) -> list[str]:
    """Source URLs anywhere in a reply: url_citation annotations, search results, grounding chunks."""
    out: list[str] = []
    if isinstance(node, dict):
        for k in ("url", "uri"):
            v = node.get(k)
            if isinstance(v, str) and v.startswith(("http://", "https://")):
                out.append(v)
        for v in node.values():
            if isinstance(v, (dict, list)):
                out += _urls(v)
    elif isinstance(node, list):
        for v in node:
            out += _urls(v)
    return list(dict.fromkeys(out))


def parse_people(text: str) -> list[CouncilPerson]:
    """The JSON object in the model's answer (tolerating fences and prose around it); [] when unusable."""
    for match in re.finditer(r"\{.*\}", text or "", re.S):
        try:
            data = _People.model_validate_json(match.group(0))
        except (ValidationError, ValueError):
            try:
                data = _People.model_validate(json.loads(match.group(0)))
            except (ValidationError, ValueError):
                continue
        return [
            CouncilPerson(
                p.name.strip()[:120],
                p.role.strip()[:120],
                p.quote.strip()[:300],
                [u for u in p.source_urls if isinstance(u, str) and u.startswith(("http://", "https://"))][:5],
            )
            for p in data.people
            if p.name.strip()
        ]
    return []


def _answer(provider: str, data: dict, fallback_cost: float) -> WebAnswer:
    text = "\n".join(_texts(data.get("output") or data.get("steps") or data))
    usage = data.get("usage") or {}
    cost = (usage.get("cost") or {}).get("total_cost") if isinstance(usage.get("cost"), dict) else None
    return WebAnswer(
        provider,
        parse_people(text),
        [u for u in _urls(data.get("output") or data.get("steps") or []) if "api.perplexity" not in u],
        float(cost) if isinstance(cost, (int, float)) else fallback_cost,
    )


# ---------------------------------------------------------------------------------------------- adapters


class KeyFailed(RuntimeError):
    """This key is rejected, out of balance or rate limited; the next key may still work."""

    def __init__(self, message: str, rest: float) -> None:
        super().__init__(message)
        self.rest = rest


async def _post(client: httpx.AsyncClient, provider: str, url: str, body: dict, headers: dict) -> dict:
    resp = await client.post(url, json=body, headers=headers)
    if resp.status_code in (401, 403):
        raise KeyFailed(f"{provider} rejected the API key", brave_keys.REJECTED_REST)
    if resp.status_code == 402:
        raise KeyFailed(f"{provider} account has no balance", brave_keys.QUOTA_REST)
    if resp.status_code == 429:
        raise KeyFailed(f"{provider} rate limit reached", brave_keys.RATE_LIMIT_REST)
    if resp.status_code >= 400:
        raise RuntimeError(f"{provider} error {resp.status_code}: {resp.text[:200]}")
    return resp.json()


async def ask_perplexity(client: httpx.AsyncClient, key: str, prompt: str) -> WebAnswer:
    s = get_settings()
    body = {
        "model": s.perplexity_model,
        "instructions": COUNCIL_SYSTEM,
        "input": prompt,
        "tools": [{"type": "web_search"}],
        "max_output_tokens": 1500,
    }
    data = await _post(
        client, "perplexity", "https://api.perplexity.ai/v1/agent", body, {"Authorization": f"Bearer {key}"}
    )
    return _answer("perplexity", data, s.cost_perplexity_per_call)


async def ask_gemini(client: httpx.AsyncClient, key: str, prompt: str) -> WebAnswer:
    s = get_settings()
    body = {
        "model": s.gemini_model,
        "system_instruction": COUNCIL_SYSTEM,
        "input": prompt,
        "tools": [{"type": "google_search"}],
    }
    data = await _post(
        client,
        "gemini",
        "https://generativelanguage.googleapis.com/v1beta/interactions",
        body,
        {"x-goog-api-key": key, "Api-Revision": "2026-05-20"},
    )
    return _answer("gemini", data, s.cost_gemini_per_call)


async def ask_openai(client: httpx.AsyncClient, key: str, prompt: str) -> WebAnswer:
    s = get_settings()
    body = {
        "model": s.openai_search_model,
        "instructions": COUNCIL_SYSTEM,
        "input": prompt,
        "tools": [{"type": "web_search"}],
        "include": ["web_search_call.action.sources"],
    }
    data = await _post(
        client, "openai", "https://api.openai.com/v1/responses", body, {"Authorization": f"Bearer {key}"}
    )
    return _answer("openai", data, s.cost_openai_search_per_call)


ADAPTERS = {"perplexity": ask_perplexity, "gemini": ask_gemini, "openai": ask_openai}


async def ask_council(
    keys: dict[str, str], business: dict, transport: httpx.AsyncBaseTransport | None = None
) -> list[WebAnswer]:
    """Ask every model with a key, in parallel. A failing model returns an answer with `error` set and no people,
    so one provider being down never blocks the others."""
    prompt = council_prompt(business)
    wanted = [p for p in COUNCIL if keys.get(p)]
    if not wanted:
        return []
    async with httpx.AsyncClient(timeout=TIMEOUT, transport=transport) as client:

        async def one(provider: str) -> WebAnswer:
            try:
                # The credential may hold several keys (one per line), used in turn like Brave's.
                failed: RuntimeError = RuntimeError(f"{provider} has no API key")
                for key in brave_keys.ordered(brave_keys.split_keys(keys[provider])):
                    try:
                        return await ADAPTERS[provider](client, key, prompt)
                    except KeyFailed as exc:
                        brave_keys.rest(key, exc.rest)
                        failed = exc
                raise failed
            except (httpx.HTTPError, RuntimeError, ValueError) as exc:
                log.info("council member failed", extra={"provider": provider, "error": str(exc)[:200]})
                return WebAnswer(provider, error=str(exc)[:300])

        return list(await asyncio.gather(*(one(p) for p in wanted)))


# ------------------------------------------------------------------------------ answers -> candidates


def to_candidates(answers: list[WebAnswer], roles: tuple[str, ...] = ()) -> list:
    """Council answers as decision-maker candidates (source "ai_research"), each carrying the pages to check:
    the URLs the model gave for that person first, then the sources its search actually returned (model-written
    URLs can be invented; search results are real pages)."""
    from app.research.enrichment.decision_makers import DecisionMaker, clean_name, is_preferred, role_rank

    out = []
    for a in answers:
        for p in a.people:
            name = clean_name(p.name)
            if not name or not (role_rank(p.role) or is_preferred(p.role, roles)):
                continue
            urls = list(dict.fromkeys([*p.urls, *a.citations[:6]]))
            dm = DecisionMaker(name, p.role or "", "ai_research", urls[0] if urls else "", p.quote, 0.5)
            dm.cited_urls = urls
            dm.vouched_by.append(f"ai:{a.provider}")
            out.append(dm)
    return out


def dump_answers(answers: list[WebAnswer]) -> str:
    return json.dumps(
        [
            {"provider": a.provider, "citations": a.citations, "people": [p.__dict__ for p in a.people]}
            for a in answers
            if not a.error
        ],
        ensure_ascii=False,
    )


def load_answers(raw: str) -> list[WebAnswer]:
    try:
        data = json.loads(raw)
        return [
            WebAnswer(d["provider"], [CouncilPerson(**p) for p in d.get("people", [])], d.get("citations", []))
            for d in data
        ]
    except (ValueError, KeyError, TypeError):
        return []
