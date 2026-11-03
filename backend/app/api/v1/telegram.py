"""Telegram account linking (admin-approved, one-time short-lived codes) and bot-facing helpers."""

import secrets
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import DB, CurrentPrincipal, audit, require_role
from app.core.config import get_settings
from app.core.errors import Conflict, NotFound, Unauthorized
from app.core.security import constant_time_equals, hash_code
from app.models import TelegramAccount, TelegramLinkCode, User, WorkspaceMember
from app.models.enums import Role, TelegramLinkStatus
from app.services.notify import notify

router = APIRouter(prefix="/telegram", tags=["telegram"])
CODE_TTL_MINUTES = 10


class LinkIn(BaseModel):
    code: str = Field(min_length=6, max_length=12)
    telegram_user_id: int
    chat_id: int
    username: str | None = Field(default=None, max_length=64)
    locale: str = "ar"  # the bot speaks Arabic unless the user picks English


def _require_service(request: Request) -> None:
    token = get_settings().telegram_service_token
    if not token or not constant_time_equals(request.headers.get("x-service-token"), token):
        raise Unauthorized("Invalid service token")


@router.post("/link-code", dependencies=[require_role(Role.ANALYST)])
async def create_link_code(p: CurrentPrincipal, db: DB) -> dict:
    code = "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(8))
    expires = datetime.now(UTC) + timedelta(minutes=CODE_TTL_MINUTES)
    db.add(
        TelegramLinkCode(user_id=p.user.id, workspace_id=p.workspace_id, code_hash=hash_code(code), expires_at=expires)
    )
    await audit(db, p, "telegram.link_code_created")
    await db.commit()
    username = (get_settings().telegram_bot_username or "").lstrip("@")
    return {
        "code": code,
        "expires_at": expires.isoformat(),
        "bot_username": username or None,
        # One tap links the account: Telegram opens the bot and sends "/start CODE" (codes use only A-Z, 2-9).
        "deep_link": f"https://t.me/{username}?start={code}" if username else None,
        "instructions": f"Send /link {code} to the bot within {CODE_TTL_MINUTES} minutes.",
    }


@router.post("/link")
async def link_account(body: LinkIn, request: Request, db: DB) -> dict:
    """Called by the bot (service token). Creates a PENDING link unless the user is an admin/owner."""
    _require_service(request)
    code = await db.scalar(select(TelegramLinkCode).where(TelegramLinkCode.code_hash == hash_code(body.code.upper())))
    now = datetime.now(UTC)
    if code is None or code.used_at is not None:
        raise Unauthorized("Invalid or already used code")
    expires = code.expires_at if code.expires_at.tzinfo else code.expires_at.replace(tzinfo=UTC)
    if expires < now:
        raise Unauthorized("Code expired")
    code.used_at = now
    member = await db.scalar(
        select(WorkspaceMember).where(
            WorkspaceMember.user_id == code.user_id, WorkspaceMember.workspace_id == code.workspace_id
        )
    )
    auto_approve = member is not None and member.role in (Role.ADMIN, Role.OWNER)
    account = await db.scalar(select(TelegramAccount).where(TelegramAccount.telegram_user_id == body.telegram_user_id))
    if account and account.user_id != code.user_id:
        raise Conflict("This Telegram account is linked to another user; ask an admin to revoke it first")
    if account is None:
        account = TelegramAccount(
            telegram_user_id=body.telegram_user_id,
            user_id=code.user_id,
            workspace_id=code.workspace_id,
            chat_id=body.chat_id,
        )
        db.add(account)
    account.chat_id = body.chat_id
    account.username = body.username
    account.locale = body.locale[:8]
    account.status = TelegramLinkStatus.APPROVED if auto_approve else TelegramLinkStatus.PENDING
    if auto_approve:
        account.approved_at = now
        account.approved_by = code.user_id
        await db.flush()
        await _linked(db, account, from_bot=True)
    await db.commit()
    return {"status": account.status}


async def link_states(db: DB, user_ids: list[uuid.UUID]) -> dict[uuid.UUID, tuple[str, str | None]]:
    """(status, username) of each user's live Telegram link; an approved account wins over a pending one."""
    if not user_ids:
        return {}
    rows = (
        await db.execute(
            select(TelegramAccount.user_id, TelegramAccount.status, TelegramAccount.username).where(
                TelegramAccount.user_id.in_(user_ids), TelegramAccount.status != TelegramLinkStatus.REVOKED
            )
        )
    ).all()
    out: dict[uuid.UUID, tuple[str, str | None]] = {}
    for uid, status, username in rows:
        state = "linked" if status == TelegramLinkStatus.APPROVED else "pending"
        if uid not in out or (state == "linked" and out[uid][0] != "linked"):
            out[uid] = (state, username)
    return out


async def _linked(db: DB, account: TelegramAccount, *, from_bot: bool = False) -> None:
    user = await db.get(User, account.user_id)
    if user is not None:
        name = f" (@{account.username})" if account.username else ""
        await notify(
            db,
            "telegram_linked",
            users=[user],
            params={"username": name},
            link="/app/settings?tab=telegram",
            # The bot already confirmed in that chat; an admin's later approval is news there.
            skip_channels={"telegram"} if from_bot else (),
        )


@router.get("/whoami")
async def whoami(p: CurrentPrincipal) -> dict:
    """Bot helper: confirms the caller is an approved linked account."""
    return {
        "user": p.user.email,
        "name": p.user.full_name,
        "role": p.role,
        "is_superuser": p.user.is_superuser,  # shows the admin menu (signup review)
        "workspace_id": str(p.workspace_id),
        "locale": p.telegram_account.locale if p.telegram_account else p.user.locale,
        "demo_mode": get_settings().demo_mode,
        "dashboard_url": get_settings().frontend_url.rstrip("/") + "/app",
    }


class LocaleIn(BaseModel):
    locale: str = Field(pattern="^(en|ar)$")


@router.post("/locale")
async def set_locale(body: LocaleIn, p: CurrentPrincipal, db: DB) -> dict:
    """Bot helper: remember the chat language so worker notifications use it too."""
    if p.telegram_account is None:
        raise NotFound("No linked Telegram account")
    p.telegram_account.locale = body.locale
    await db.commit()
    return {"locale": body.locale}


@router.post("/status")
async def account_status(request: Request, db: DB, telegram_user_id: int) -> dict:
    _require_service(request)
    account = await db.scalar(select(TelegramAccount).where(TelegramAccount.telegram_user_id == telegram_user_id))
    return {"status": account.status if account else "unlinked"}


@router.get("/accounts")
async def list_accounts(p: CurrentPrincipal, db: DB) -> list[dict]:
    q = (
        select(TelegramAccount, User)
        .join(User, User.id == TelegramAccount.user_id)
        .where(TelegramAccount.workspace_id == p.workspace_id)
    )
    if p.role not in (Role.ADMIN, Role.OWNER):
        q = q.where(TelegramAccount.user_id == p.user.id)
    rows = (await db.execute(q.order_by(TelegramAccount.created_at.desc()))).all()
    return [
        {
            "id": str(a.id),
            "user_email": u.email,
            "telegram_user_id": a.telegram_user_id,
            "username": a.username,
            "status": a.status,
            "created_at": a.created_at.isoformat(),
            "approved_at": a.approved_at.isoformat() if a.approved_at else None,
        }
        for a, u in rows
    ]


async def _account(db: DB, p: CurrentPrincipal, account_id: uuid.UUID) -> TelegramAccount:
    a = await db.scalar(
        select(TelegramAccount).where(TelegramAccount.id == account_id, TelegramAccount.workspace_id == p.workspace_id)
    )
    if a is None:
        raise NotFound("Telegram account not found")
    return a


@router.post("/accounts/{account_id}/approve", dependencies=[require_role(Role.ADMIN)])
async def approve(account_id: uuid.UUID, p: CurrentPrincipal, db: DB) -> dict:
    a = await _account(db, p, account_id)
    a.status = TelegramLinkStatus.APPROVED
    a.approved_by = p.user.id
    a.approved_at = datetime.now(UTC)
    await audit(db, p, "telegram.approved", "telegram_account", a.id)
    await db.flush()
    await _linked(db, a)
    await db.commit()
    return {"status": a.status}


@router.post("/accounts/{account_id}/revoke")
async def revoke(account_id: uuid.UUID, p: CurrentPrincipal, db: DB) -> dict:
    a = await _account(db, p, account_id)
    if a.user_id != p.user.id:
        p.require(Role.ADMIN)
    a.status = TelegramLinkStatus.REVOKED
    await audit(db, p, "telegram.revoked", "telegram_account", a.id)
    await db.commit()
    return {"status": a.status}
