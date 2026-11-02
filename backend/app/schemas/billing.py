import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.models.enums import CreditKind, PaymentMethod, TopUpStatus
from app.schemas.common import ORM


class BillingSummary(BaseModel):
    billing_exempt: bool
    balance: int
    on_trial: bool
    trial_ends_at: datetime | None
    trial_days_left: int | None
    trial_expired: bool
    # A self-signup whose free trial starts once the owner confirms their email.
    awaiting_verification: bool = False
    credits_per_contact: int
    low_balance: bool
    pending_topups: int
    payment_instructions_ar: str
    payment_instructions_en: str
    paypal_enabled: bool = False  # the store's PayPal account is connected


class TransactionOut(ORM):
    id: uuid.UUID
    delta: int
    balance_after: int
    kind: CreditKind
    campaign_id: uuid.UUID | None
    business_id: uuid.UUID | None
    note: str | None
    created_at: datetime


class PackageOut(ORM):
    id: uuid.UUID
    name_ar: str
    name_en: str
    credits: int
    price: Decimal
    currency: str
    featured: bool = False


class TopUpIn(BaseModel):
    package_id: uuid.UUID
    method: PaymentMethod
    reference: str | None = Field(default=None, max_length=200)
    receipt_filename: str = Field(min_length=1, max_length=200)
    # 5 MB file, base64-encoded (~6.7 MB)
    receipt_base64: str = Field(min_length=1, max_length=7_000_000)


class TopUpOut(ORM):
    id: uuid.UUID
    package_id: uuid.UUID | None
    credits: int
    amount: Decimal
    currency: str
    method: PaymentMethod
    reference: str | None
    receipt_filename: str | None
    status: TopUpStatus
    reason: str | None
    created_at: datetime
    reviewed_at: datetime | None


class PayPalOrderIn(BaseModel):
    package_id: uuid.UUID


class PayPalOrderOut(BaseModel):
    order_id: str
    approve_url: str


class PayPalOrderRef(BaseModel):
    order_id: str = Field(min_length=1, max_length=64)
