"""CSV / XLSX exports. UTF-8 with BOM so Excel renders Arabic correctly. Missing data stays empty —
never a placeholder that could look like real contact data."""

import csv
import io
import uuid

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Business, BusinessSource, Campaign, LeadAssessment, LeadNote, WorkspaceProfile
from app.models.enums import ContactType, VerificationStatus
from app.services.leads import PUBLIC_PROOF_KINDS, LeadFilters, best_contact, decorate, lead_query
from app.services.profile import offering_map, offering_name

COLUMNS = [
    "Company",
    "Industry",
    "Country",
    "City",
    "Website",
    "General email",
    "Email status",
    "Phone",
    "Phone status",
    "WhatsApp",
    "Decision maker",
    "Decision maker role",
    "Decision maker email",
    "Decision maker phone",
    "Decision maker WhatsApp",
    "Decision maker LinkedIn",
    "Decision maker proof",
    "Contact page",
    "Social links",
    "Source URLs",
    "Lead score",
    "Priority",
    "Recommended service",
    "AI opportunity",
    "Observed signals",
    "Unknowns",
    "CRM status",
    "Outreach eligible",
    "Notes",
    "Demo record",
]
MAX_EXPORT = 10_000


def decision_maker_cells(contacts: list) -> list[str]:
    """The verified decision maker (never an unproven name): name, role, their own channels and proof pages."""
    people = [
        c
        for c in contacts
        if c.type == ContactType.PERSON and c.verification_status == VerificationStatus.VERIFIED and c.person_name
    ]
    if not people:
        return [""] * 7
    top = max(people, key=lambda c: c.confidence)

    def own(ctype: ContactType) -> str:
        found = [
            c
            for c in contacts
            if c.type == ctype
            and c.person_name == top.person_name
            and not c.is_suppressed
            and c.verification_status != VerificationStatus.INVALID
        ]
        return max(found, key=lambda c: c.confidence).normalized_value if found else ""

    linkedin = next(
        (
            c.value
            for c in contacts
            if c.type == ContactType.SOCIAL and c.person_name == top.person_name and "linkedin.com/in/" in c.value
        ),
        "",
    )
    proofs = [p["url"] for p in (top.evidence or {}).get("proofs", []) if p.get("kind") in PUBLIC_PROOF_KINDS]
    return [
        top.person_name or "",
        top.person_role or "",
        own(ContactType.EMAIL),
        own(ContactType.PHONE),
        own(ContactType.WHATSAPP),
        linkedin,
        " | ".join(proofs[:3]),
    ]


async def export_rows(db: AsyncSession, workspace_id: uuid.UUID, f: LeadFilters) -> list[list]:
    businesses = list(
        await db.scalars(
            lead_query(workspace_id, f).order_by(Business.latest_score.desc().nulls_last()).limit(MAX_EXPORT)
        )
    )
    decorated = await decorate(db, workspace_id, businesses)
    offerings = offering_map(
        await db.scalar(select(WorkspaceProfile).where(WorkspaceProfile.workspace_id == workspace_id))
    )
    ids = [b.id for b in businesses]
    assessments: dict[uuid.UUID, LeadAssessment] = {}
    for a in await db.scalars(
        select(LeadAssessment).where(LeadAssessment.business_id.in_(ids)).order_by(LeadAssessment.created_at)
    ):
        assessments[a.business_id] = a
    notes: dict[uuid.UUID, list[str]] = {}
    for n in await db.scalars(select(LeadNote).where(LeadNote.business_id.in_(ids)).order_by(LeadNote.created_at)):
        notes.setdefault(n.business_id, []).append(n.body)
    source_urls: dict[uuid.UUID, list[str]] = {}
    for bid, url in (
        await db.execute(
            select(BusinessSource.business_id, BusinessSource.source_url).where(BusinessSource.business_id.in_(ids))
        )
    ).all():
        source_urls.setdefault(bid, []).append(url)

    rows = []
    for b, d in zip(businesses, decorated, strict=True):
        contacts = d["_contacts"]
        email = best_contact(contacts, ContactType.EMAIL)
        phone = best_contact(contacts, ContactType.PHONE)
        wa = best_contact(contacts, ContactType.WHATSAPP)
        page = next((c for c in contacts if c.type == ContactType.CONTACT_PAGE), None)
        social = [c.value for c in contacts if c.type == ContactType.SOCIAL]
        a = assessments.get(b.id)
        service = offering_name(offerings, b.recommended_service)
        rows.append(
            [
                b.name,
                b.industry or "",
                b.country or "",
                b.city or "",
                b.website_url or "",
                email.value if email else "",
                email.verification_status if email else "",
                phone.normalized_value if phone else "",
                phone.verification_status if phone else "",
                wa.normalized_value if wa else "",
                *decision_maker_cells(contacts),
                page.value if page else "",
                " | ".join(social),
                " | ".join(source_urls.get(b.id, [])),
                b.latest_score if b.latest_score is not None else "",
                b.latest_priority or "",
                service,
                a.opportunity if a else "",
                " | ".join(s.get("signal", "") for s in (a.observed_signals if a else [])),
                " | ".join(a.unknowns if a else []),
                b.crm_status,
                "yes" if d["outreach_eligible"] else "no",
                " | ".join(notes.get(b.id, [])),
                "yes" if b.is_demo else "no",
            ]
        )
    return rows


def to_csv(rows: list[list]) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(COLUMNS)
    for r in rows:
        writer.writerow([_safe_cell(v) for v in r])
    return ("﻿" + buf.getvalue()).encode("utf-8")


def _safe_cell(v: object) -> object:
    """Neutralise spreadsheet formula injection from scraped text."""
    if isinstance(v, str) and v[:1] in ("=", "+", "-", "@") and not v[1:2].isdigit():
        return "'" + v
    return v


def to_xlsx(rows: list[list], summary: dict | None = None) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Leads"
    ws.append(COLUMNS)
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="0E0F31")
    for r in rows:
        ws.append([_safe_cell(v) for v in r])
    for col in ws.columns:
        ws.column_dimensions[col[0].column_letter].width = min(max(len(str(c.value or "")) for c in col[:50]) + 2, 50)
    ws.freeze_panes = "A2"
    if summary:
        s = wb.create_sheet("Campaign summary")
        for k, v in summary.items():
            s.append([k, str(v) if isinstance(v, (dict, list)) else v])
        s.column_dimensions["A"].width = 32
        s.column_dimensions["B"].width = 60
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def campaign_summary(c: Campaign) -> dict:
    s = c.stats or {}
    return {
        "Campaign": c.name,
        "Demo mode": "yes" if c.is_demo else "no",
        "Status": c.status,
        "Country": c.country,
        "City": c.city or "",
        "Industry": c.industry,
        "Sources": ", ".join(f"{x.provider_key} ({x.status}, {x.results_count})" for x in c.sources),
        "Requested leads (target)": s.get("target"),
        "Businesses discovered": s.get("discovered"),
        "Duplicates removed": s.get("duplicates_removed"),
        "Unique businesses": s.get("unique_leads"),
        "Qualified leads": s.get("qualified"),
        "High priority": s.get("high_priority"),
        "Businesses with contacts": s.get("businesses_with_contacts"),
        "Emails found": s.get("emails_found"),
        "Verified emails": s.get("verified_emails"),
        "Analysis provider": s.get("ai_provider"),
        "Discovery cost (USD)": c.cost_discovery,
        "AI cost (USD)": c.cost_ai,
        "Started": c.started_at.isoformat() if c.started_at else "",
        "Completed": c.completed_at.isoformat() if c.completed_at else "",
        "Notes": c.last_error or "",
    }
