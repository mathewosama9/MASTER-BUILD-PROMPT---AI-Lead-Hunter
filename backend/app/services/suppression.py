"""Workspace-wide suppression. A suppressed prospect can never become outreach-eligible again,
regardless of which campaign rediscovers it."""

import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Business, BusinessContact, SuppressionEntry
from app.models.enums import ContactType, CrmStatus, SuppressionKind
from app.research.enrichment.normalize import normalize_domain, normalize_email, normalize_phone


def normalize_suppression(kind: str, value: str) -> str | None:
    value = value.strip()
    if kind == SuppressionKind.DOMAIN:
        return normalize_domain(value)
    if kind == SuppressionKind.EMAIL:
        return normalize_email(value)
    if kind == SuppressionKind.PHONE:
        return normalize_phone(value, None) or (value if value.startswith("+") else None)
    if kind == SuppressionKind.BUSINESS:
        return str(uuid.UUID(value))
    return None


async def suppression_sets(db: AsyncSession, workspace_id: uuid.UUID) -> dict[str, set[str]]:
    rows = await db.execute(
        select(SuppressionEntry.kind, SuppressionEntry.value).where(SuppressionEntry.workspace_id == workspace_id)
    )
    out: dict[str, set[str]] = {k.value: set() for k in SuppressionKind}
    for kind, value in rows.all():
        out.setdefault(kind, set()).add(value)
    return out


def contact_is_suppressed(contact_type: str, normalized_value: str, sets: dict[str, set[str]]) -> bool:
    if contact_type == ContactType.EMAIL:
        return normalized_value in sets["email"] or normalized_value.split("@")[-1] in sets["domain"]
    if contact_type in (ContactType.PHONE, ContactType.WHATSAPP):
        return normalized_value in sets["phone"]
    return False


def business_is_suppressed(business: Business, sets: dict[str, set[str]]) -> bool:
    return (
        business.crm_status == CrmStatus.DO_NOT_CONTACT
        or str(business.id) in sets["business"]
        or (business.normalized_domain is not None and business.normalized_domain in sets["domain"])
    )


async def apply_suppression(db: AsyncSession, workspace_id: uuid.UUID) -> int:
    """Re-evaluate suppression flags for all contacts/businesses in the workspace. Returns affected count."""
    sets = await suppression_sets(db, workspace_id)
    affected = 0
    if sets["domain"]:
        res = await db.execute(
            update(Business)
            .where(
                Business.workspace_id == workspace_id,
                Business.normalized_domain.in_(sets["domain"]),
                Business.crm_status != CrmStatus.DO_NOT_CONTACT,
            )
            .values(crm_status=CrmStatus.DO_NOT_CONTACT)
        )
        affected += res.rowcount or 0
    if sets["business"]:
        ids = [uuid.UUID(b) for b in sets["business"]]
        res = await db.execute(
            update(Business)
            .where(
                Business.workspace_id == workspace_id,
                Business.id.in_(ids),
                Business.crm_status != CrmStatus.DO_NOT_CONTACT,
            )
            .values(crm_status=CrmStatus.DO_NOT_CONTACT)
        )
        affected += res.rowcount or 0
    contacts = await db.scalars(
        select(BusinessContact)
        .join(Business, Business.id == BusinessContact.business_id)
        .where(Business.workspace_id == workspace_id)
    )
    for c in contacts:
        flag = contact_is_suppressed(c.type, c.normalized_value, sets)
        if flag != c.is_suppressed:
            c.is_suppressed = flag
            affected += 1
    await db.flush()
    return affected


def outreach_eligible(business: Business, contacts: list[BusinessContact], sets: dict[str, set[str]]) -> bool:
    if business_is_suppressed(business, sets):
        return False
    return any(
        not c.is_suppressed
        and not contact_is_suppressed(c.type, c.normalized_value, sets)
        and c.type in (ContactType.EMAIL, ContactType.PHONE, ContactType.WHATSAPP)
        and c.verification_status != "invalid"
        for c in contacts
    )
