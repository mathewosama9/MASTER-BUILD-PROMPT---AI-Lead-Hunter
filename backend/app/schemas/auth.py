import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.core.countries import ISO_COUNTRIES
from app.models.enums import Role
from app.schemas.common import ORM

# Hash of browser traits computed by the dashboard (lib/device.ts); helps spot a second account on the same machine.
DeviceFingerprint = Annotated[str | None, Field(pattern="^[a-f0-9]{16,128}$")]


def clean_phone(v: str) -> str:
    """7-15 digits, an optional leading +, spaces, dashes and brackets; shared by signup and admin edits."""
    v = v.strip()
    digits = sum(ch.isdigit() for ch in v)
    if not 7 <= digits <= 15 or any(ch not in "+0123456789 -()" for ch in v) or "+" in v[1:]:
        raise ValueError("Enter a valid phone number")
    return v


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)
    device_fp: DeviceFingerprint = None


class RegisterIn(BaseModel):
    full_name: str = Field(min_length=2, max_length=200)
    company: str = Field(min_length=2, max_length=200)
    email: EmailStr
    phone: str = Field(min_length=7, max_length=32)
    password: str = Field(min_length=10, max_length=200)
    nationality: str = Field(min_length=2, max_length=2)
    locale: Literal["ar", "en"] = "ar"
    device_fp: DeviceFingerprint = None

    @field_validator("nationality")
    @classmethod
    def _country(cls, v: str) -> str:
        v = v.upper()
        if v not in ISO_COUNTRIES:
            raise ValueError("Choose a country")
        return v

    @field_validator("full_name", "company")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = " ".join(v.split())
        if len(v) < 2:
            raise ValueError("Too short")
        return v

    @field_validator("phone")
    @classmethod
    def _phone(cls, v: str) -> str:
        return clean_phone(v)


class UserOut(ORM):
    id: uuid.UUID
    email: str
    full_name: str
    is_active: bool
    is_superuser: bool = False
    locale: str
    last_login_at: datetime | None = None
    email_verified_at: datetime | None = None
    nationality: str | None = None
    approval_status: str = "approved"


class MeOut(BaseModel):
    user: UserOut
    workspace_id: uuid.UUID
    workspace_name: str
    role: Role
    csrf_token: str | None = None
    access_token: str | None = None
    demo_mode: bool
    # Drives the "link Telegram" strip on every dashboard page
    telegram_status: Literal["linked", "pending", "none"] = "none"
    telegram_username: str | None = None
    # Email of the platform admin viewing this account (read-only), if any
    impersonated_by: str | None = None


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=200)
    full_name: str = Field(default="", max_length=200)
    role: Role = Role.ANALYST


class MemberOut(BaseModel):
    user: UserOut
    role: Role


class MemberUpdate(BaseModel):
    role: Role | None = None
    is_active: bool | None = None
    full_name: str | None = Field(default=None, max_length=200)


class ForgotPasswordIn(BaseModel):
    email: EmailStr


class ResetPasswordIn(BaseModel):
    token: str = Field(min_length=10, max_length=2000)
    password: str = Field(min_length=10, max_length=200)


class VerifyEmailIn(BaseModel):
    token: str = Field(min_length=10, max_length=2000)


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=10, max_length=200)
