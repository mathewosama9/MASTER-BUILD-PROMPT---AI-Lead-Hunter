"""Workspace profile: the offerings a workspace sells and its ideal customer profile (ICP).

Offerings replace the fixed service catalog the product shipped with: analysis may only recommend ids from the
workspace's own list, scoring measures relevance against them and pitches describe them.
"""

import re
import secrets
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import WorkspaceProfile
from app.research.catalog import LEGACY_SERVICES

MAX_OFFERINGS = 12
ONBOARDING_STEPS = 6


def new_offering_id() -> str:
    return f"o_{secrets.token_hex(4)}"


async def get_profile(db: AsyncSession, workspace_id: uuid.UUID) -> WorkspaceProfile:
    """The workspace's profile, created empty the first time (not committed)."""
    p = await db.scalar(select(WorkspaceProfile).where(WorkspaceProfile.workspace_id == workspace_id))
    if p is None:
        p = WorkspaceProfile(
            workspace_id=workspace_id,
            offerings=[],
            target_industries=[],
            target_countries=[],
            target_cities=[],
            company_sizes=[],
            good_signals=[],
            disqualifiers=[],
            channels=[],
        )
        db.add(p)
        await db.flush()
    return p


def clean_offerings(items: list[dict]) -> list[dict]:
    """Normalise user-submitted offerings: trim, drop blanks and duplicate names, keep or assign stable ids."""
    out: list[dict] = []
    seen_ids: set[str] = set()
    seen_names: set[str] = set()
    for raw in items:
        name = str(raw.get("name") or "").strip()[:120]
        if not name or name.casefold() in seen_names:
            continue
        oid = str(raw.get("id") or "").strip()[:40]
        if not re.fullmatch(r"[A-Za-z0-9_\-]{2,40}", oid) or oid in seen_ids:
            oid = new_offering_id()
        keywords = [str(k).strip()[:60] for k in (raw.get("keywords") or []) if str(k).strip()][:15]
        out.append(
            {
                "id": oid,
                "name": name,
                "description": str(raw.get("description") or "").strip()[:600],
                "keywords": keywords,
            }
        )
        seen_ids.add(oid)
        seen_names.add(name.casefold())
        if len(out) == MAX_OFFERINGS:
            break
    return out


def offering_map(profile: WorkspaceProfile | None) -> dict[str, dict]:
    return {o["id"]: o for o in (profile.offerings if profile else []) or [] if o.get("id")}


def offering_name(offerings: dict[str, dict], key: str | None, lang: str = "en") -> str:
    """Display name for an offering id; falls back to the legacy catalog label, then the raw key."""
    if not key:
        return ""
    if key in offerings:
        return offerings[key]["name"]
    legacy = LEGACY_SERVICES.get(key)
    if legacy:
        return legacy["ar" if lang == "ar" else "en"]
    return key


def seller_context(profile: WorkspaceProfile | None, wanted: list[str] | None = None) -> dict:
    """What the AI needs to know about the seller. `wanted` narrows the offerings to a campaign's selection."""
    if profile is None:
        return {}
    offers = profile.offerings or []
    if wanted:
        chosen = [o for o in offers if o.get("id") in set(wanted)]
        offers = chosen or offers
    return {
        "company": profile.company_name,
        "what_we_do": profile.description,
        "value_proposition": profile.value_proposition,
        "offerings": [
            {
                "id": o["id"],
                "name": o["name"],
                "description": o.get("description", ""),
                "keywords": o.get("keywords", []),
            }
            for o in offers
            if o.get("id")
        ],
        "ideal_customer": {
            "industries": profile.target_industries,
            "company_sizes": profile.company_sizes,
            "good_signals": profile.good_signals,
            "disqualifiers": profile.disqualifiers,
        },
    }


def onboarding_state(profile: WorkspaceProfile | None) -> dict:
    return {
        "step": profile.onboarding_step if profile else 0,
        "completed": bool(profile and profile.onboarding_completed_at),
        "steps": ONBOARDING_STEPS,
    }
