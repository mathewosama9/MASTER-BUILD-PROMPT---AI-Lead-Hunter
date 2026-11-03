"""Who an admin broadcast goes to. Every audience resolves to a query of user ids."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import Select, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CreditTransaction, User, Workspace, WorkspaceMember
from app.models.enums import ApprovalStatus, CreditKind
from app.services.credits import LOW_BALANCE_CREDITS

SEGMENTS = ("all", "admins", "trial", "paying", "low_balance", "inactive_30d", "suspended", "users", "workspaces")


def _purchased():
    return exists().where(CreditTransaction.workspace_id == Workspace.id, CreditTransaction.kind == CreditKind.PURCHASE)


def _members_where(*conditions) -> Select:  # noqa: ANN002
    return (
        select(WorkspaceMember.user_id)
        .join(Workspace, Workspace.id == WorkspaceMember.workspace_id)
        .where(Workspace.deleted_at.is_(None), *conditions)
    )


def user_ids_query(audience: dict) -> Select:
    """Distinct ids of active users in `audience` ({"type": segment, "ids": [...]})."""
    kind = audience.get("type")
    ids = [uuid.UUID(str(i)) for i in audience.get("ids") or []]
    now = datetime.now(UTC)
    if kind == "admins":
        inner = select(User.id).where(User.is_superuser.is_(True))
    elif kind == "trial":
        inner = _members_where(Workspace.trial_ends_at.is_not(None), Workspace.trial_ends_at > now, ~_purchased())
    elif kind == "paying":
        inner = _members_where(_purchased())
    elif kind == "low_balance":
        inner = _members_where(
            Workspace.billing_exempt.is_(False),
            Workspace.credit_balance < LOW_BALANCE_CREDITS,
            Workspace.suspended_at.is_(None),
        )
    elif kind == "inactive_30d":
        cutoff = now - timedelta(days=30)
        inner = select(User.id).where((User.last_login_at.is_(None)) | (User.last_login_at < cutoff))
    elif kind == "suspended":
        inner = _members_where(Workspace.suspended_at.is_not(None))
    elif kind == "users":
        inner = select(User.id).where(User.id.in_(ids))
    elif kind == "workspaces":
        inner = _members_where(Workspace.id.in_(ids))
    else:  # all
        inner = select(User.id)
    return (
        select(User.id)
        .where(
            User.id.in_(inner),
            User.is_active.is_(True),
            User.deleted_at.is_(None),
            # Rejected signups can't sign in and never agreed to hear from us.
            User.approval_status != ApprovalStatus.REJECTED,
        )
        .order_by(User.created_at)
    )


async def count(db: AsyncSession, audience: dict) -> int:
    q = user_ids_query(audience).order_by(None).subquery()
    return int(await db.scalar(select(func.count()).select_from(q)) or 0)
