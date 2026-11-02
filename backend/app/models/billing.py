"""Credits: platform-wide pricing settings, credit packages, the per-workspace ledger and manual top-ups.

1 credit buys `credits_per_contact`-th of a delivered contact: a business new to the workspace that a campaign
delivered with at least one usable phone, WhatsApp or email (see `services/credits.py`).
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, Integer, LargeBinary, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, JSONType, Timestamps, UUIDPk
from app.models.enums import TopUpStatus


class PlatformSettings(Timestamps, Base):
    """Single row (id = 1) edited by the platform admin."""

    __tablename__ = "platform_settings"
    __table_args__ = (CheckConstraint("id = 1", name="single_row"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    trial_days: Mapped[int] = mapped_column(Integer, default=30)
    trial_credits: Mapped[int] = mapped_column(Integer, default=100)
    credits_per_contact: Mapped[int] = mapped_column(Integer, default=1)
    payment_instructions_ar: Mapped[str] = mapped_column(Text, default="")
    payment_instructions_en: Mapped[str] = mapped_column(Text, default="")
    # The platform's own workspace whose searches feed the public site's live preview. Customer workspaces are
    # never read for the preview.
    showcase_workspace_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("workspaces.id", ondelete="SET NULL"))
    # Research settings applied to every client campaign (schemas/campaign.py ResearchDefaults); {} = defaults.
    research_defaults: Mapped[dict] = mapped_column(JSONType, default=dict)


class CreditPackage(UUIDPk, Timestamps, Base):
    __tablename__ = "credit_packages"

    name_ar: Mapped[str] = mapped_column(String(120))
    name_en: Mapped[str] = mapped_column(String(120))
    credits: Mapped[int] = mapped_column(Integer)
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    featured: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")  # "most popular" tag
    sort: Mapped[int] = mapped_column(Integer, default=0)


class CreditTransaction(UUIDPk, Timestamps, Base):
    """Append-only ledger. `balance_after` is the workspace balance right after this row was applied."""

    __tablename__ = "credit_transactions"
    __table_args__ = (Index("ix_credit_transactions_ws_created", "workspace_id", "created_at"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    delta: Mapped[int] = mapped_column(Integer)
    balance_after: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(20))  # CreditKind
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("campaigns.id", ondelete="SET NULL"))
    business_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("businesses.id", ondelete="SET NULL"))
    note: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class ContactRequest(UUIDPk, Timestamps, Base):
    """A demo / consultation request from the public site's contact form."""

    __tablename__ = "contact_requests"

    name: Mapped[str] = mapped_column(String(200))
    company: Mapped[str | None] = mapped_column(String(200))
    email: Mapped[str] = mapped_column(String(320))
    phone: Mapped[str | None] = mapped_column(String(32))
    interest: Mapped[str] = mapped_column(String(30))  # ContactInterest
    message: Mapped[str] = mapped_column(Text, default="")
    locale: Mapped[str] = mapped_column(String(8), default="ar")
    ip: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(10), default="new", index=True)  # new | handled
    handled_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    handled_at: Mapped[datetime | None]


class TopUpRequest(UUIDPk, Timestamps, Base):
    """A credit purchase: a PayPal order (approved automatically once captured) or a legacy manual payment
    (InstaPay / bank transfer / Vodafone Cash with a receipt) reviewed by the admin."""

    __tablename__ = "topup_requests"

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    package_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("credit_packages.id", ondelete="SET NULL"))
    credits: Mapped[int] = mapped_column(Integer)  # snapshot of the package at request time
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    method: Mapped[str] = mapped_column(String(20))  # PaymentMethod
    reference: Mapped[str | None] = mapped_column(String(200))
    receipt_filename: Mapped[str | None] = mapped_column(String(500))  # as uploaded; display only
    receipt_content_type: Mapped[str | None] = mapped_column(String(100))  # detected from the bytes, not the name
    # Kept in the database (small, rare, backed up with everything else); loaded only when the receipt is opened.
    receipt_data: Mapped[bytes | None] = mapped_column(LargeBinary, deferred=True)
    status: Mapped[str] = mapped_column(String(10), default=TopUpStatus.PENDING, index=True)
    reason: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    reviewed_at: Mapped[datetime | None]
    transaction_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("credit_transactions.id", ondelete="SET NULL"))
    provider_order_id: Mapped[str | None] = mapped_column(String(64), unique=True)  # PayPal order id
    provider_capture_id: Mapped[str | None] = mapped_column(String(64))
