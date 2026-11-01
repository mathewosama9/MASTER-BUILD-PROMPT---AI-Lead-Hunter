import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, CheckConstraint, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, JSONType, SoftDelete, Timestamps, UUIDPk
from app.models.enums import Role, TelegramLinkStatus


class User(UUIDPk, Timestamps, SoftDelete, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(200), default="")
    phone: Mapped[str | None] = mapped_column(String(32))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False)
    locale: Mapped[str] = mapped_column(String(8), default="en")
    last_login_at: Mapped[datetime | None]
    # Set when the user opens the confirmation link; self-signup trials start then.
    email_verified_at: Mapped[datetime | None]

    memberships: Mapped[list["WorkspaceMember"]] = relationship(back_populates="user", lazy="selectin")


class Workspace(UUIDPk, Timestamps, SoftDelete, Base):
    __tablename__ = "workspaces"
    __table_args__ = (CheckConstraint("credit_balance >= 0", name="credit_balance_non_negative"),)

    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(100), unique=True)
    # scoring weights, retention days, default services, etc.
    settings: Mapped[dict] = mapped_column(JSONType, default=dict)
    # Credits (see services/credits.py). Change the balance only through the ledger functions there.
    credit_balance: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    trial_ends_at: Mapped[datetime | None]
    billing_exempt: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    # Set by the platform admin: members can no longer sign in or run campaigns.
    suspended_at: Mapped[datetime | None]

    members: Mapped[list["WorkspaceMember"]] = relationship(back_populates="workspace")


class WorkspaceProfile(UUIDPk, Timestamps, Base):
    """What the workspace sells and who it sells to. Drives onboarding, search planning, analysis and pitches."""

    __tablename__ = "workspace_profiles"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), unique=True, index=True
    )
    company_name: Mapped[str] = mapped_column(String(200), default="", server_default="")
    website: Mapped[str | None] = mapped_column(String(500))
    business_category: Mapped[str | None] = mapped_column(String(60))  # key from catalog.PROVIDER_CATEGORIES
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    value_proposition: Mapped[str] = mapped_column(Text, default="", server_default="")
    # [{id, name, description, keywords[]}]: the services this workspace sells. Leads recommend these ids.
    offerings: Mapped[list] = mapped_column(JSONType, default=list)
    # Ideal customer profile
    target_industries: Mapped[list] = mapped_column(JSONType, default=list)
    target_countries: Mapped[list] = mapped_column(JSONType, default=list)
    target_cities: Mapped[list] = mapped_column(JSONType, default=list)
    company_sizes: Mapped[list] = mapped_column(JSONType, default=list)
    good_signals: Mapped[list] = mapped_column(JSONType, default=list)
    disqualifiers: Mapped[list] = mapped_column(JSONType, default=list)
    # Outreach
    sender_name: Mapped[str] = mapped_column(String(120), default="", server_default="")
    outreach_language: Mapped[str] = mapped_column(String(8), default="ar", server_default="ar")
    tone: Mapped[str] = mapped_column(String(32), default="professional", server_default="professional")
    channels: Mapped[list] = mapped_column(JSONType, default=list)
    # Onboarding progress: the furthest step saved, and when the wizard was finished (or skipped).
    onboarding_step: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    onboarding_completed_at: Mapped[datetime | None]


class WorkspaceMember(UUIDPk, Timestamps, Base):
    __tablename__ = "workspace_members"
    __table_args__ = (UniqueConstraint("workspace_id", "user_id"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(20), default=Role.ANALYST)

    user: Mapped[User] = relationship(back_populates="memberships")
    workspace: Mapped[Workspace] = relationship(back_populates="members", lazy="joined")


class TelegramAccount(UUIDPk, Timestamps, Base):
    __tablename__ = "telegram_accounts"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    chat_id: Mapped[int] = mapped_column(BigInteger)
    username: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default=TelegramLinkStatus.PENDING)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    approved_at: Mapped[datetime | None]
    locale: Mapped[str] = mapped_column(String(8), default="en")


class TelegramLinkCode(UUIDPk, Timestamps, Base):
    __tablename__ = "telegram_link_codes"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    code_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime]
    used_at: Mapped[datetime | None]
