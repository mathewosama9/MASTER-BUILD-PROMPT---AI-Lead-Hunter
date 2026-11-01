import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.models.enums import Role
from app.schemas.common import ORM


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


class RegisterIn(BaseModel):
    full_name: str = Field(min_length=2, max_length=200)
    company: str = Field(min_length=2, max_length=200)
    email: EmailStr
    phone: str = Field(min_length=7, max_length=32)
    password: str = Field(min_length=10, max_length=200)
    locale: Literal["ar", "en"] = "ar"

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
        v = v.strip()
        digits = sum(ch.isdigit() for ch in v)
        if not 7 <= digits <= 15 or any(ch not in "+0123456789 -()" for ch in v) or "+" in v[1:]:
            raise ValueError("Enter a valid phone number")
        return v


class UserOut(ORM):
    id: uuid.UUID
    email: str
    full_name: str
    is_active: bool
    is_superuser: bool = False
    locale: str
    last_login_at: datetime | None = None
    email_verified_at: datetime | None = None


class MeOut(BaseModel):
    user: UserOut
    workspace_id: uuid.UUID
    workspace_name: str
    role: Role
    csrf_token: str | None = None
    access_token: str | None = None
    demo_mode: bool


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
