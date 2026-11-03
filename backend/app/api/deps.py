"""Authentication & authorization dependencies.

Three ways to authenticate, all resolving to the same `Principal`:
1. Browser: httpOnly session cookie + double-submit CSRF header on unsafe methods.
2. API clients: `Authorization: Bearer <jwt>`.
3. Telegram bot: `X-Service-Token` + `X-Telegram-User-Id` of an *approved* linked account.
"""

import uuid
from dataclasses import dataclass
from typing import Annotated

import jwt
from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_db
from app.core.errors import Forbidden, Unauthorized
from app.core.security import constant_time_equals, decode_access_token, password_fingerprint
from app.models import AuditLog, TelegramAccount, User, WorkspaceMember
from app.models.enums import ROLE_RANK, ApprovalStatus, Role, TelegramLinkStatus
from app.services import presence

SESSION_COOKIE = "lh_session"
ADMIN_SESSION_COOKIE = "lh_admin_session"  # the admin's own session, kept while viewing a customer's account
# The only write allowed while viewing a customer's account (going back uses the admin's own session, not this one).
IMPERSONATION_WRITES = ("/api/v1/auth/logout",)
CSRF_COOKIE = "lh_csrf"
CSRF_HEADER = "x-csrf-token"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

DB = Annotated[AsyncSession, Depends(get_db)]


@dataclass
class Principal:
    user: User
    workspace_id: uuid.UUID
    role: Role
    via: str  # web | api | telegram
    telegram_account: TelegramAccount | None = None
    impersonator: User | None = None  # set while a platform admin views this account (read-only)

    def require(self, role: Role) -> None:
        if ROLE_RANK[self.role] < ROLE_RANK[role]:
            raise Forbidden(f"Requires {role.value} role")


async def _membership(db: AsyncSession, user_id: uuid.UUID, workspace_id: uuid.UUID | None) -> WorkspaceMember | None:
    q = select(WorkspaceMember).where(WorkspaceMember.user_id == user_id)
    if workspace_id:
        q = q.where(WorkspaceMember.workspace_id == workspace_id)
    return await db.scalar(q.order_by(WorkspaceMember.created_at).limit(1))


async def get_principal(request: Request, db: DB) -> Principal:
    settings = get_settings()

    service_token = request.headers.get("x-service-token")
    if service_token is not None:
        if not settings.telegram_service_token or not constant_time_equals(
            service_token, settings.telegram_service_token
        ):
            raise Unauthorized("Invalid service token")
        tg_id = request.headers.get("x-telegram-user-id", "")
        if not tg_id.lstrip("-").isdigit():
            raise Unauthorized("Missing Telegram user id")
        account = await db.scalar(select(TelegramAccount).where(TelegramAccount.telegram_user_id == int(tg_id)))
        if account is None or account.status != TelegramLinkStatus.APPROVED:
            raise Forbidden("Telegram account is not linked or not approved")
        user = await db.get(User, account.user_id)
        member = await _membership(db, account.user_id, account.workspace_id)
        if user is None or not user.is_active or user.deleted_at or member is None:
            raise Forbidden("Linked user is inactive")
        _check_not_suspended(user, member)
        await presence.touch(request, user, "telegram")
        return Principal(user, account.workspace_id, Role(member.role), "telegram", account)

    token: str | None = None
    via = "api"
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
    else:
        token = request.cookies.get(SESSION_COOKIE)
        via = "web"
        if token and request.method not in SAFE_METHODS:
            if not constant_time_equals(request.headers.get(CSRF_HEADER), request.cookies.get(CSRF_COOKIE)):
                raise Forbidden("CSRF token missing or invalid")
    if not token:
        raise Unauthorized("Not authenticated")
    try:
        payload = decode_access_token(token)
    except jwt.PyJWTError as exc:
        raise Unauthorized("Session expired or invalid") from exc
    user = await db.get(User, uuid.UUID(payload["sub"]))
    if user is None or not user.is_active or user.deleted_at is not None:
        raise Unauthorized("User inactive")
    # Sessions issued before a password change or reset are no longer valid.
    if "pv" in payload and payload["pv"] != password_fingerprint(user.password_hash):
        raise Unauthorized("Session expired or invalid")
    member = await _membership(db, user.id, uuid.UUID(payload["ws"]))
    if member is None:
        raise Forbidden("No access to this workspace")
    if "imp" in payload:
        admin = await db.get(User, uuid.UUID(payload["imp"]))
        if admin is None or not admin.is_superuser or not admin.is_active or admin.deleted_at is not None:
            raise Unauthorized("Session expired or invalid")
        if request.method not in SAFE_METHODS and request.url.path not in IMPERSONATION_WRITES:
            raise Forbidden(
                "Viewing a customer's account is read-only · عرض حساب العميل للمشاهدة بس",
                code="impersonation_read_only",
            )
        # No presence.touch: the customer's "last seen" must not move while an admin looks around.
        return Principal(user, member.workspace_id, Role(member.role), via, impersonator=admin)
    _check_not_suspended(user, member)
    await presence.touch(request, user, via)
    return Principal(user, member.workspace_id, Role(member.role), via)


def _check_not_suspended(user: User, member: WorkspaceMember) -> None:
    if user.approval_status == ApprovalStatus.REJECTED:
        raise Forbidden("This account was not approved. Contact support.", code="account_rejected")
    # Platform admins keep access so they can always reach /admin (and lift a suspension).
    if member.workspace.suspended_at is not None and not user.is_superuser:
        raise Forbidden("This workspace is suspended. Contact support.", code="workspace_suspended")


CurrentPrincipal = Annotated[Principal, Depends(get_principal)]


async def _superuser(p: CurrentPrincipal) -> Principal:
    if not p.user.is_superuser:
        raise Forbidden("Platform admins only")
    return p


SuperPrincipal = Annotated[Principal, Depends(_superuser)]


def require_role(role: Role):  # noqa: ANN201
    async def _dep(p: CurrentPrincipal) -> Principal:
        p.require(role)
        return p

    return Depends(_dep)


async def audit(
    db: AsyncSession,
    p: Principal | None,
    action: str,
    entity_type: str | None = None,
    entity_id: object = None,
    data: dict | None = None,
    ip: str | None = None,
) -> None:
    data = dict(data or {})
    if p and p.impersonator:  # an admin viewing the account did it, not the customer
        data["as_user"] = p.user.email
    db.add(
        AuditLog(
            workspace_id=p.workspace_id if p else None,
            user_id=(p.impersonator or p.user).id if p else None,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id else None,
            data=data,
            ip=ip,
            via=p.via if p else "system",
        )
    )
