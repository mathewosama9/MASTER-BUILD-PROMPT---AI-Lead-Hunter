"""A signed-in user's own review of the product. Published on the site only with consent and after admin approval."""

import logging

from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import DB, CurrentPrincipal, audit
from app.core.ratelimit import enforce
from app.models import Testimonial, Workspace, WorkspaceProfile
from app.models.enums import TestimonialSource, TestimonialStatus
from app.schemas.marketing import MyReviewOut, ReviewIn
from app.services.notify import notify_admins

log = logging.getLogger(__name__)
router = APIRouter(prefix="/reviews", tags=["reviews"])


@router.get("/mine", response_model=MyReviewOut | None)
async def my_review(p: CurrentPrincipal, db: DB) -> MyReviewOut | None:
    r = await db.scalar(
        select(Testimonial).where(Testimonial.user_id == p.user.id).order_by(Testimonial.created_at.desc()).limit(1)
    )
    return MyReviewOut.model_validate(r) if r else None


@router.post("", response_model=MyReviewOut, status_code=201)
async def submit_review(body: ReviewIn, p: CurrentPrincipal, db: DB) -> MyReviewOut:
    """One review per user: sending again replaces it and puts it back in the admin's queue."""
    await enforce(f"review:{p.user.id}", 5, 3600)
    profile = await db.scalar(select(WorkspaceProfile).where(WorkspaceProfile.workspace_id == p.workspace_id))
    ws = await db.get(Workspace, p.workspace_id)
    r = await db.scalar(select(Testimonial).where(Testimonial.user_id == p.user.id).limit(1))
    if r is None:
        r = Testimonial(user_id=p.user.id, source=TestimonialSource.IN_APP)
        db.add(r)
    arabic = (p.user.locale or "ar") == "ar"
    r.workspace_id = p.workspace_id
    r.author_name = (p.user.full_name or p.user.email.split("@")[0])[:120]
    r.company = (profile.company_name if profile and profile.company_name else None) or (ws.name if ws else None)
    r.author_role = body.author_role or None
    r.city = body.city or None
    r.rating = body.rating
    r.body_ar = body.body.strip() if arabic else ""
    r.body_en = "" if arabic else body.body.strip()
    r.consent_publish = body.consent_publish
    r.status = TestimonialStatus.PENDING
    r.reviewed_at = None
    await db.flush()
    await audit(db, p, "review.submitted", "testimonial", r.id, {"rating": body.rating})
    await notify_admins(
        db,
        "admin_review",
        {
            "rating": r.rating,
            "author": r.author_name + (f" · {r.company}" if r.company else ""),
            "consent": "✓" if r.consent_publish else "✗",
            "body": (r.body_ar or r.body_en)[:1500],
        },
        link="/app/admin?tab=testimonials",
    )
    await db.commit()
    return MyReviewOut.model_validate(r)
