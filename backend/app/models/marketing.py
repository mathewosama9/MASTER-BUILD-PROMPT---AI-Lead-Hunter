"""Marketing content shown on the public site: customer testimonials."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Timestamps, UUIDPk


class Testimonial(UUIDPk, Timestamps, Base):
    """A review shown on the public site once approved.

    `source`: `in_app` (a user left it from the dashboard, with consent), `manual` (the admin added one received
    elsewhere) or `sample` (placeholder copy that must be replaced before launch; the admin is warned while any
    sample is still published).
    """

    __tablename__ = "testimonials"
    __table_args__ = (
        CheckConstraint("rating BETWEEN 1 AND 5", name="rating_range"),
        Index("ix_testimonials_public", "status", "is_featured", "sort"),
    )

    author_name: Mapped[str] = mapped_column(String(120))
    author_role: Mapped[str | None] = mapped_column(String(120))
    company: Mapped[str | None] = mapped_column(String(200))
    city: Mapped[str | None] = mapped_column(String(120))
    country: Mapped[str | None] = mapped_column(String(2))
    rating: Mapped[int] = mapped_column(Integer, default=5)
    body_ar: Mapped[str] = mapped_column(Text, default="", server_default="")
    body_en: Mapped[str] = mapped_column(Text, default="", server_default="")
    source: Mapped[str] = mapped_column(String(10), default="manual")  # TestimonialSource
    status: Mapped[str] = mapped_column(String(10), default="pending", index=True)  # TestimonialStatus
    is_featured: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    sort: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    consent_publish: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("workspaces.id", ondelete="SET NULL"))
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    reviewed_at: Mapped[datetime | None]
