"""Deduplication.

Identity keys, in order: normalized business domain, E.164 phone, then a stable listing id from the source
(`gmaps:<cid>`, `osm:<type>/<id>`, `social:<profile url>`). Names are NEVER used to merge records
(two "Smile Dental" clinics in different cities are different businesses).
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

    @property
    def all(self) -> list[BusinessCandidate]:
        return [self.primary, *self.duplicates]


def identity_key(c: BusinessCandidate) -> str | None:
    domain = business_domain(c.website_url)
    if domain:
        return f"domain:{domain}"
    phone = normalize_phone(c.phone, c.country) if c.phone else None
    if phone:
        return f"phone:{phone}"
    for kind in LISTING_ID_KINDS:
        if c.identifiers.get(kind):
            return f"{kind}:{c.identifiers[kind]}"
    return None


def dedupe_candidates(candidates: list[BusinessCandidate]) -> tuple[list[CandidateGroup], int]:
    """Group in-batch duplicates. Candidates without any identity key are kept as distinct groups."""
    groups: dict[str, CandidateGroup] = {}
    ordered: list[CandidateGroup] = []
    removed = 0
    for i, c in enumerate(candidates):
        key = identity_key(c)
        if key and key in groups:
            groups[key].duplicates.append(c)
            removed += 1
            continue
        group = CandidateGroup(key=key or f"unkeyed:{i}", primary=c)
        if key:
            groups[key] = group
        ordered.append(group)
    return ordered, removed


async def find_existing_business(db: AsyncSession, workspace_id: uuid.UUID, key: str) -> Business | None:
    kind, _, value = key.partition(":")
    base = select(Business).where(Business.workspace_id == workspace_id, Business.deleted_at.is_(None))
    if kind == "domain":
        return await db.scalar(base.where(Business.normalized_domain == value))
    if kind == "phone" or kind in LISTING_ID_KINDS:
        return await db.scalar(base.where(Business.identifiers[kind].as_string() == value).limit(1))
    return None
