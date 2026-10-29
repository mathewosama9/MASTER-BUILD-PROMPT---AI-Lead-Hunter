import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from app.models.enums import Role
from app.schemas.common import ORM


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


class UserOut(ORM):
    id: uuid.UUID
    email: str
    full_name: str
    is_active: bool
    locale: str
    last_login_at: datetime | None = None


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


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=10, max_length=200)
