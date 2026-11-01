import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class PublicTestimonialOut(BaseModel):
    """What the public site shows: never the source, status or who submitted it."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    author_name: str
    author_role: str | None
    company: str | None
    city: str | None
    country: str | None
    rating: int
    body_ar: str
    body_en: str
    is_featured: bool


class TestimonialOut(PublicTestimonialOut):
    __test__ = False  # not a pytest test class

    source: str
    status: str
    sort: int
    consent_publish: bool
    workspace_id: uuid.UUID | None
    user_id: uuid.UUID | None
    created_at: datetime
    reviewed_at: datetime | None


class ReviewIn(BaseModel):
    rating: int = Field(ge=1, le=5)
    body: str = Field(min_length=10, max_length=1000)
    author_role: str | None = Field(default=None, max_length=120)
    city: str | None = Field(default=None, max_length=120)
    consent_publish: bool = False


class MyReviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    rating: int
    status: str
    consent_publish: bool
    created_at: datetime
