import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Query, Request
from fastapi.responses import Response

from app.api.deps import DB, CurrentPrincipal, audit
from app.api.v1.leads import Filters
from app.core.errors import AppError, Conflict
from app.integrations.google_sheets import SheetsError, export_to_sheet
from app.services import campaigns as campaign_svc
from app.services import providers as provider_svc
from app.services.exports import COLUMNS, campaign_summary, export_rows, to_csv, to_xlsx
from app.services.leads import LeadFilters

router = APIRouter(prefix="/exports", tags=["exports"])


def _filename(prefix: str, ext: str) -> str:
    return f"{prefix}-{datetime.now(UTC).strftime('%Y%m%d-%H%M')}.{ext}"


@router.get("/leads")
async def export_leads(
    p: CurrentPrincipal,
    db: DB,
    request: Request,
    f: LeadFilters = Filters,
    format: str = Query("csv", pattern="^(csv|xlsx)$"),
    ids: str | None = Query(None, description="Comma-separated lead ids"),
) -> Response:
    if ids:
        f.ids = [uuid.UUID(i) for i in ids.split(",") if i]
    rows = await export_rows(db, p.workspace_id, f)
    await audit(
        db,
        p,
        "export.leads",
        None,
        None,
        {"format": format, "rows": len(rows)},
        request.client.host if request.client else None,
    )
    await db.commit()
    if format == "xlsx":
        return Response(
            to_xlsx(rows),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{_filename("leads", "xlsx")}"'},
        )
    return Response(
        to_csv(rows),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{_filename("leads", "csv")}"'},
    )


@router.get("/campaigns/{campaign_id}")
async def export_campaign(
    campaign_id: uuid.UUID,
    p: CurrentPrincipal,
    db: DB,
    format: str = Query("xlsx", pattern="^(csv|xlsx)$"),
    qualified_only: bool = False,
) -> Response:
    c = await campaign_svc.get_campaign(db, p.workspace_id, campaign_id)
    rows = await export_rows(db, p.workspace_id, LeadFilters(campaign_id=c.id, qualified_only=qualified_only or None))
    await audit(db, p, "export.campaign", "campaign", c.id, {"format": format, "rows": len(rows)})
    await db.commit()
    slug = "".join(ch if ch.isalnum() else "-" for ch in c.name.lower())[:40] or "campaign"
    if format == "csv":
        return Response(
            to_csv(rows),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{_filename(slug, "csv")}"'},
        )
    return Response(
        to_xlsx(rows, campaign_summary(c)),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{_filename(slug, "xlsx")}"'},
    )


@router.get("/campaigns/{campaign_id}/summary")
async def campaign_report(campaign_id: uuid.UUID, p: CurrentPrincipal, db: DB) -> dict:
    c = await campaign_svc.get_campaign(db, p.workspace_id, campaign_id)
    return campaign_summary(c)


@router.post("/google-sheets")
async def export_google_sheets(
    p: CurrentPrincipal, db: DB, f: LeadFilters = Filters, title: str = Query("AI Lead Hunter export", max_length=100)
) -> dict:
    creds, _ = await provider_svc.credentials_for(db, p.workspace_id, "google_sheets")
    if not creds.get("credentials_json"):
        raise Conflict("Google Sheets is not configured (add service-account JSON in Settings → Integrations)")
    rows = await export_rows(db, p.workspace_id, f)
    try:
        url = await export_to_sheet(creds["credentials_json"], title, COLUMNS, rows, share_with=p.user.email)
    except SheetsError as exc:
        raise AppError(str(exc), status_code=502, code="google_sheets_error") from exc
    await audit(db, p, "export.google_sheets", None, None, {"rows": len(rows)})
    await db.commit()
    return {"url": url, "rows": len(rows)}
