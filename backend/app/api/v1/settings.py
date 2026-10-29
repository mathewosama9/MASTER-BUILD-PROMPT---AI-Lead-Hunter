from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import DB, CurrentPrincipal, audit, require_role
from app.core.config import get_settings
from app.models import AuditLog, Workspace
from app.models.enums import Role
from app.research.catalog import COUNTRIES, INDUSTRIES, SERVICES
from app.research.scoring.scorer import DEFAULT_THRESHOLDS, DEFAULT_WEIGHTS, SCORING_VERSION

router = APIRouter(tags=["settings"])


class WorkspaceSettingsIn(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    scoring_weights: dict[str, float] | None = None
    scoring_thresholds: dict[str, float] | None = None
    retention_days: int | None = Field(default=None, ge=30, le=3650)
    allow_named_contacts: bool | None = None
    default_services: list[str] | None = None
    sender_name: str | None = Field(default=None, max_length=120)


@router.get("/meta")
async def meta() -> dict:
    """Reference data for the dashboard and bot (no auth needed; contains no tenant data)."""
    return {
        "demo_mode": get_settings().demo_mode,
        "countries": [
            {
                "code": c["code"],
                "name_en": c["name_en"],
                "name_ar": c["name_ar"],
                "cities": [{"en": en, "ar": ar} for en, ar in c["cities"]],
            }
            for c in COUNTRIES.values()
        ],
        "industries": [{"key": i["key"], "en": i["en"], "ar": i["ar"]} for i in INDUSTRIES.values()],
        "services": [{"key": k, **v} for k, v in SERVICES.items()],
        "scoring": {"weights": DEFAULT_WEIGHTS, "thresholds": DEFAULT_THRESHOLDS, "version": SCORING_VERSION},
    }


@router.get("/settings")
async def get_workspace_settings(p: CurrentPrincipal, db: DB) -> dict:
    ws = await db.get(Workspace, p.workspace_id)
    s = ws.settings or {}
    return {
        "name": ws.name,
        "scoring_weights": {**DEFAULT_WEIGHTS, **s.get("scoring_weights", {})},
        "scoring_thresholds": {**DEFAULT_THRESHOLDS, **s.get("scoring_thresholds", {})},
        "retention_days": s.get("retention_days", get_settings().data_retention_days),
        "allow_named_contacts": s.get("allow_named_contacts", False),
        "default_services": s.get("default_services", []),
        "sender_name": s.get("sender_name", ""),
        "demo_mode": get_settings().demo_mode,
    }


@router.put("/settings", dependencies=[require_role(Role.ADMIN)])
async def update_workspace_settings(body: WorkspaceSettingsIn, p: CurrentPrincipal, db: DB) -> dict:
    ws = await db.get(Workspace, p.workspace_id)
    s = dict(ws.settings or {})
    data = body.model_dump(exclude_none=True)
    if "name" in data:
        ws.name = data.pop("name")
    if "scoring_weights" in data:
        data["scoring_weights"] = {
            k: max(0.0, float(v)) for k, v in data["scoring_weights"].items() if k in DEFAULT_WEIGHTS
        }
    if "scoring_thresholds" in data:
        data["scoring_thresholds"] = {
            k: float(v) for k, v in data["scoring_thresholds"].items() if k in DEFAULT_THRESHOLDS
        }
    s.update(data)
    ws.settings = s
    await audit(db, p, "settings.updated", "workspace", ws.id, data)
    await db.commit()
    return await get_workspace_settings(p, db)


@router.get("/settings/audit-logs", dependencies=[require_role(Role.ADMIN)])
async def audit_logs(p: CurrentPrincipal, db: DB, limit: int = Query(100, ge=1, le=500)) -> list[dict]:
    rows = await db.scalars(
        select(AuditLog)
        .where(AuditLog.workspace_id == p.workspace_id)
        .order_by(AuditLog.created_at.desc())
        .limit(limit)
    )
    return [
        {
            "id": str(a.id),
            "action": a.action,
            "entity_type": a.entity_type,
            "entity_id": a.entity_id,
            "user_id": str(a.user_id) if a.user_id else None,
            "via": a.via,
            "data": a.data,
            "ip": a.ip,
            "created_at": a.created_at.isoformat(),
        }
        for a in rows
    ]
