"""Deduplication.

Identity keys: normalized business domain, E.164 phone, and stable listing ids from the source (`gmaps:<cid>`,
`osm:<type>/<id>`, `social:<profile url>`). A record matches on ANY of its keys, so a Maps listing that only shows
the phone joins the record found earlier through the website - except that two different domains are never
merged, even when they share a phone (franchises, call centres, a directory's own number). Names are NEVER used to
merge records (two "Smile Dental" clinics in different cities are different businesses).
"""

import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Business
from app.research.enrichment.normalize import business_domain, normalize_phone
from app.research.providers.base import BusinessCandidate

# Source listing ids usable as identity keys, most specific first.
LISTING_ID_KINDS = ("gmaps", "osm", "social", "directory")


@dataclass
class CandidateGroup:
    key: str
    primary: BusinessCandidate
    duplicates: list[BusinessCandidate] = field(default_factory=list)
    keys: list[str] = field(default_factory=list)
    domain: str | None = None

    @property
    def all(self) -> list[BusinessCandidate]:
        return [self.primary, *self.duplicates]

    @property
    def website_url(self) -> str | None:
        """The first published website among the group's listings (the primary may be a Maps pin without one)."""
        return next((c.website_url for c in self.all if business_domain(c.website_url)), self.primary.website_url)

    @property
    def phone(self) -> str | None:
        for c in self.all:
            phone = normalize_phone(c.phone, c.country) if c.phone else None
            if phone:
                return phone
        return None


def identity_keys(c: BusinessCandidate) -> list[str]:
    keys: list[str] = []
    domain = business_domain(c.website_url)
    if domain:
        keys.append(f"domain:{domain}")
    phone = normalize_phone(c.phone, c.country) if c.phone else None
    if phone:
        keys.append(f"phone:{phone}")
    keys += [f"{kind}:{c.identifiers[kind]}" for kind in LISTING_ID_KINDS if c.identifiers.get(kind)]
    return keys


def identity_key(c: BusinessCandidate) -> str | None:
    keys = identity_keys(c)
    return keys[0] if keys else None


def dedupe_candidates(candidates: list[BusinessCandidate]) -> tuple[list[CandidateGroup], int]:
    """Group in-batch duplicates. Candidates without any identity key are kept as distinct groups."""
    by_key: dict[str, CandidateGroup] = {}
    ordered: list[CandidateGroup] = []
    removed = 0
    for i, c in enumerate(candidates):
        keys = identity_keys(c)
        domain = business_domain(c.website_url)
        group = next(
            (g for k in keys if (g := by_key.get(k)) and not (domain and g.domain and g.domain != domain)),
            None,
        )
        if group is not None:
            group.duplicates.append(c)
            group.domain = group.domain or domain
            group.keys += [k for k in keys if k not in group.keys]
            removed += 1
        else:
            group = CandidateGroup(key=keys[0] if keys else f"unkeyed:{i}", primary=c, keys=list(keys), domain=domain)
            ordered.append(group)
        for k in keys:
            by_key.setdefault(k, group)
    for g in ordered:  # the domain is the strongest key once any listing in the group has one
        if g.domain:
            g.key = f"domain:{g.domain}"
    return ordered, removed


async def find_existing_business(
    db: AsyncSession, workspace_id: uuid.UUID, key: str | list[str], domain: str | None = None
) -> Business | None:
    """The workspace's record for any of `key`; a phone/listing match owned by another domain is not this one."""
    base = select(Business).where(Business.workspace_id == workspace_id, Business.deleted_at.is_(None))
    for k in [key] if isinstance(key, str) else key:
        kind, _, value = k.partition(":")
        if kind == "domain":
            found = await db.scalar(base.where(Business.normalized_domain == value))
        elif kind == "phone" or kind in LISTING_ID_KINDS:
            found = await db.scalar(base.where(Business.identifiers[kind].as_string() == value).limit(1))
        else:
            continue
        if found is not None and not (domain and found.normalized_domain and found.normalized_domain != domain):
            return found
    return None
