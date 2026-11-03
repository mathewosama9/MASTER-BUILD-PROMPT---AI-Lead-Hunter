import re
import secrets
import uuid
from datetime import UTC, datetime

import jwt
from fastapi import APIRouter, BackgroundTasks, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from app.api.deps import (
    ADMIN_SESSION_COOKIE,
    CSRF_COOKIE,
    CSRF_HEADER,
    DB,
    SESSION_COOKIE,
    CurrentPrincipal,
    audit,
    require_role,
)
from app.api.v1.telegram import link_states
from app.core.config import get_settings
from app.core.errors import AppError, Conflict, Forbidden, NotFound, Unauthorized
from app.core.ratelimit import enforce
from app.core.security import (
    ALGORITHM,
    constant_time_equals,
    create_access_token,
    decode_access_token,
    hash_password,
    new_csrf_token,
    password_fingerprint,
    verify_password,
)
from app.models import AuditLog, TelegramAccount, TelegramLinkCode, User, Workspace, WorkspaceMember
from app.models.enums import ApprovalStatus, Role, TelegramLinkStatus
from app.schemas.auth import (
    ForgotPasswordIn,
    LoginIn,
    MemberOut,
    MemberUpdate,
    MeOut,
    PasswordChange,
    RegisterIn,
    ResetPasswordIn,
    UserCreate,
    UserOut,
    VerifyEmailIn,
)
from app.schemas.common import Message
from app.services import accounts
from app.services import signup_review as review
from app.services.notify import notify

router = APIRouter(prefix="/auth", tags=["auth"])
users_router = APIRouter(prefix="/users", tags=["users"])


def _set_session(response: Response, token: str, csrf: str, minutes: int | None = None) -> None:
    s = get_settings()
    common = {
        "secure": s.cookie_secure,
        "samesite": "lax",
        "domain": s.cookie_domain,
        "path": "/",
        "max_age": (minutes or s.access_token_minutes) * 60,
    }
    response.set_cookie(SESSION_COOKIE, token, httponly=True, **common)
    response.set_cookie(CSRF_COOKIE, csrf, httponly=False, **common)


@router.post("/login", response_model=MeOut)
async def login(
    body: LoginIn, request: Request, response: Response, background: BackgroundTasks, db: DB
) -> MeOut:
    email = body.email.lower()
    # Per address: password guessing against one account is slowed whatever IPs it comes from.
    await enforce(f"login:{password_fingerprint(email)}", get_settings().login_limit_per_email, 900)
    user = await db.scalar(select(User).where(func.lower(User.email) == email, User.deleted_at.is_(None)))
    # Hash even for an unknown address, so the reply time does not reveal which emails have accounts.
    password_ok = verify_password(body.password, user.password_hash if user else _DUMMY_HASH)
    if user is None or not user.is_active or not password_ok:
        raise Unauthorized("Invalid email or password")
    if user.approval_status == ApprovalStatus.REJECTED:
        raise Forbidden("This account was not approved. Contact support.", code="account_rejected")
    member = await db.scalar(
        select(WorkspaceMember).where(WorkspaceMember.user_id == user.id).order_by(WorkspaceMember.created_at).limit(1)
    )
    if member is None:
        raise Unauthorized("User has no workspace")
    return await _start_session(
        db, request, response, user, member, "auth.login", body.device_fp, background=background
    )


_DUMMY_HASH = hash_password("timing-equaliser-not-a-real-password")


def _device_id(request: Request, response: Response) -> str:
    """The browser's long-lived id, set on first sign-in; a second account from the same browser shares it."""
    device = request.cookies.get(review.DEVICE_COOKIE, "")
    if not re.fullmatch(r"[a-f0-9]{32}", device):
        device = review.new_device_id()
    s = get_settings()
    response.set_cookie(
        review.DEVICE_COOKIE,
        device,
        max_age=review.DEVICE_COOKIE_DAYS * 86400,
        httponly=True,
        secure=s.cookie_secure,
        samesite="lax",
        domain=s.cookie_domain,
        path="/",
    )
    return device


async def _start_session(
    db: DB,
    request: Request,
    response: Response,
    user: User,
    member: WorkspaceMember,
    action: str,
    fingerprint: str | None = None,
    *,
    with_identity: bool = False,
    commit: bool = True,
    background: BackgroundTasks | None = None,
) -> MeOut:
    user.last_login_at = datetime.now(UTC)
    new_signal = await review.record(
        db,
        user,
        ip=_ip(request),
        device=_device_id(request, response),
        fingerprint=fingerprint,
        user_agent=request.headers.get("user-agent"),
        with_identity=with_identity,
    )
    user.last_seen_at, user.last_seen_ip = user.last_login_at, review.public_ip(_ip(request))
    token = create_access_token(user.id, member.workspace_id, password_hash=user.password_hash)
    csrf = new_csrf_token()
    _set_session(response, token, csrf)
    db.add(
        AuditLog(
            workspace_id=member.workspace_id,
            user_id=user.id,
            action=action,
            ip=request.client.host if request.client else None,
        )
    )
    if commit:
        await db.commit()
    if new_signal and background is not None:  # after the commit, outside this transaction's row locks
        background.add_task(review.refresh_counts_soon, user.id, new_signal)
    ws = await db.get(Workspace, member.workspace_id)
    return MeOut(
        user=UserOut.model_validate(user),
        workspace_id=member.workspace_id,
        workspace_name=ws.name if ws else "",
        role=Role(member.role),
        csrf_token=csrf,
        access_token=token,
        demo_mode=get_settings().demo_mode,
    )


def _slug(company: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", company.lower()).strip("-")[:60] or "workspace"
    return f"{base}-{secrets.token_hex(4)}"


async def _revoke_telegram(db: DB, user_id: uuid.UUID) -> None:
    """Telegram links authenticate without the session cookie, so a password change must cut them off too:
    linked chats are revoked and unused link codes burnt (e.g. someone who signed up with this email first)."""
    await db.execute(
        update(TelegramAccount)
        .where(TelegramAccount.user_id == user_id, TelegramAccount.status != TelegramLinkStatus.REVOKED)
        .values(status=TelegramLinkStatus.REVOKED)
    )
    await db.execute(
        update(TelegramLinkCode)
        .where(TelegramLinkCode.user_id == user_id, TelegramLinkCode.used_at.is_(None))
        .values(used_at=datetime.now(UTC))
    )


def _ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@router.post("/register", response_model=MeOut, status_code=201)
async def register(
    body: RegisterIn, request: Request, response: Response, background: BackgroundTasks, db: DB
) -> MeOut:
    """Self-signup: a new workspace owned by the caller. The free trial (from the platform settings) starts once the
    owner has confirmed their email and the platform admin has approved the account (services/signup_review.py),
    so one person gets one trial."""
    await enforce(f"signup:{_ip(request)}", get_settings().signup_limit_per_hour, 3600)
    email = body.email.lower()
    if await db.scalar(select(User.id).where(func.lower(User.email) == email)):
        raise Conflict("An account with this email already exists; sign in instead", code="email_taken")
    user = User(
        email=email,
        password_hash=hash_password(body.password),
        full_name=body.full_name,
        phone=body.phone,
        nationality=body.nationality,
        locale=body.locale,
        approval_status=ApprovalStatus.PENDING,
        signup_ip=review.public_ip(_ip(request)),
    )
    workspace = Workspace(name=body.company, slug=_slug(body.company), settings={})
    db.add_all([user, workspace])
    try:
        await db.flush()
    except IntegrityError as exc:  # a concurrent signup with the same email won the race
        await db.rollback()
        raise Conflict("An account with this email already exists; sign in instead", code="email_taken") from exc
    member = WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role=Role.OWNER)
    db.add(member)
    me = await _start_session(
        db, request, response, user, member, "auth.registered", body.device_fp, with_identity=True, commit=False
    )
    found = await review.matches(db, user.id)
    if not await review.needs_review(db, found):
        user.approval_status = ApprovalStatus.APPROVED
        me.user.approval_status = ApprovalStatus.APPROVED
    await review.notify_signup(db, user, body.company, found)
    await db.commit()
    background.add_task(accounts.send_verification, user.id)
    background.add_task(review.after_signup, user.id)  # stored counts, and signups made at the same moment
    return me


_RESET_SENT = "If an account exists for this email, we sent a link to reset the password."


@router.post("/password/forgot", response_model=Message, status_code=202)
async def forgot_password(body: ForgotPasswordIn, request: Request, background: BackgroundTasks, db: DB) -> Message:
    """Email a reset link. Same reply whether or not the account exists."""
    email = body.email.lower()
    await enforce(f"pwreset:{_ip(request)}", get_settings().password_reset_limit_per_hour, 3600)
    await enforce(f"pwreset-email:{password_fingerprint(email)}", 3, 3600)
    user = await db.scalar(select(User).where(func.lower(User.email) == email, User.deleted_at.is_(None)))
    if user is not None and user.is_active:
        background.add_task(accounts.send_password_reset, user.id)
        db.add(AuditLog(user_id=user.id, action="auth.password_reset_requested", ip=_ip(request), via="web"))
        await db.commit()
    return Message(message=_RESET_SENT)


_BAD_RESET = "This reset link is invalid or has expired; request a new one"


@router.post("/password/reset", response_model=Message)
async def reset_password(body: ResetPasswordIn, request: Request, db: DB) -> Message:
    claims = accounts.decode_reset(body.token)
    if claims is None:
        raise AppError(_BAD_RESET, code="invalid_token")
    user = await db.scalar(select(User).where(User.id == uuid.UUID(claims["sub"])).with_for_update())
    # The token names the password hash it was issued for: once the password changes it stops working.
    if (
        user is None
        or not user.is_active
        or user.deleted_at is not None
        or claims.get("pv") != password_fingerprint(user.password_hash)
    ):
        raise AppError(_BAD_RESET, code="invalid_token")
    user.password_hash = hash_password(body.password)  # also signs out every existing session
    await _revoke_telegram(db, user.id)
    await accounts.mark_verified(db, user)  # the reset link proves the user reads this inbox
    await notify(db, "password_changed", users=[user])
    db.add(AuditLog(user_id=user.id, action="auth.password_reset", ip=_ip(request), via="web"))
    await db.commit()
    return Message(message="Password updated; sign in with the new password")


@router.post("/email/verify", response_model=Message)
async def verify_email(body: VerifyEmailIn, request: Request, db: DB) -> Message:
    claims = accounts.decode_verify(body.token)
    user = None
    if claims is not None:
        user = await db.scalar(select(User).where(User.id == uuid.UUID(claims["sub"])).with_for_update())
    if user is None or user.deleted_at is not None or claims.get("email") != user.email.lower():
        raise AppError("This confirmation link is invalid or has expired", code="invalid_token")
    if await accounts.mark_verified(db, user):
        db.add(AuditLog(user_id=user.id, action="auth.email_verified", ip=_ip(request), via="web"))
    await db.commit()
    return Message(message="Email confirmed")


@router.post("/email/resend", response_model=Message, status_code=202)
async def resend_verification(p: CurrentPrincipal, background: BackgroundTasks) -> Message:
    if p.user.email_verified_at is not None:
        raise Conflict("Your email is already confirmed", code="already_verified")
    await enforce(f"verify-resend:{p.user.id}", get_settings().verify_resend_limit_per_hour, 3600)
    background.add_task(accounts.send_verification, p.user.id)
    return Message(message="Confirmation email sent")


@router.post("/logout", response_model=Message)
async def logout(response: Response) -> Message:
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
    response.delete_cookie(ADMIN_SESSION_COOKIE, path="/")
    return Message(message="Logged out")


@router.post("/impersonation/stop")
async def stop_impersonation(request: Request, response: Response, db: DB) -> dict:
    """Leave a customer's account and go back to the admin's own session (kept aside when viewing started).

    It needs no valid customer session, so it still works after the 30-minute view has run out."""
    if not constant_time_equals(request.headers.get(CSRF_HEADER), request.cookies.get(CSRF_COOKIE)):
        raise Forbidden("CSRF token missing or invalid")
    admin_token = request.cookies.get(ADMIN_SESSION_COOKIE) or ""
    admin: User | None = None
    try:
        payload = decode_access_token(admin_token)
        if "imp" not in payload:
            admin = await db.get(User, uuid.UUID(payload["sub"]))
    except (jwt.PyJWTError, KeyError, ValueError):
        admin = None
    if admin is not None and (not admin.is_superuser or not admin.is_active or admin.deleted_at is not None):
        admin = None
    # Who was being viewed: read from the customer session even if it expired, only to log it and go back to them.
    viewed: User | None = None
    viewed_ws: uuid.UUID | None = None
    try:
        current = jwt.decode(
            request.cookies.get(SESSION_COOKIE) or "",
            get_settings().secret_key,
            algorithms=[ALGORITHM],
            options={"verify_exp": False},
        )
        if admin is not None and current.get("imp") == str(admin.id):
            viewed, viewed_ws = await db.get(User, uuid.UUID(current["sub"])), uuid.UUID(current["ws"])
    except (jwt.PyJWTError, KeyError, ValueError):
        viewed = None
    response.delete_cookie(ADMIN_SESSION_COOKIE, path="/")
    if admin is None:  # nothing to go back to (the admin's own session ran out too): sign out completely
        response.delete_cookie(SESSION_COOKIE, path="/")
        response.delete_cookie(CSRF_COOKIE, path="/")
        return {"user_id": None, "signed_out": True}
    if viewed is not None:
        db.add(
            AuditLog(
                workspace_id=viewed_ws,
                user_id=admin.id,
                action="admin.impersonation_stopped",
                entity_type="user",
                entity_id=str(viewed.id),
                data={"email": viewed.email},
                ip=request.client.host if request.client else None,
            )
        )
        await db.commit()
    _set_session(response, admin_token, request.cookies.get(CSRF_COOKIE) or new_csrf_token())
    return {"user_id": str(viewed.id) if viewed else None, "signed_out": False}


@router.get("/me", response_model=MeOut)
async def me(p: CurrentPrincipal, request: Request, db: DB) -> MeOut:
    ws = await db.get(Workspace, p.workspace_id)
    tg_status, tg_username = (await link_states(db, [p.user.id])).get(p.user.id, ("none", None))
    return MeOut(
        user=UserOut.model_validate(p.user),
        workspace_id=p.workspace_id,
        workspace_name=ws.name if ws else "",
        role=p.role,
        csrf_token=request.cookies.get(CSRF_COOKIE),
        demo_mode=get_settings().demo_mode,
        telegram_status=tg_status,
        telegram_username=tg_username,
        impersonated_by=p.impersonator.email if p.impersonator else None,
    )


@router.post("/password", response_model=Message)
async def change_password(
    body: PasswordChange, p: CurrentPrincipal, request: Request, response: Response, db: DB
) -> Message:
    if not verify_password(body.current_password, p.user.password_hash):
        raise Unauthorized("Current password is incorrect")
    p.user.password_hash = hash_password(body.new_password)  # signs out other sessions
    await _revoke_telegram(db, p.user.id)
    await audit(db, p, "auth.password_changed", "user", p.user.id)
    await notify(db, "password_changed", users=[p.user])
    await db.commit()
    if p.via == "web":  # keep this browser signed in
        token = create_access_token(p.user.id, p.workspace_id, password_hash=p.user.password_hash)
        _set_session(response, token, request.cookies.get(CSRF_COOKIE) or new_csrf_token())
    return Message(message="Password updated")


class LocaleIn(BaseModel):
    locale: str = Field(pattern="^(ar|en)$")


@router.put("/locale", response_model=Message)
async def set_locale(body: LocaleIn, p: CurrentPrincipal, db: DB) -> Message:
    """The dashboard language, so emails and notifications follow it instead of the signup language."""
    if p.user.locale != body.locale:
        p.user.locale = body.locale
        await db.commit()
    return Message(message="ok")


@users_router.get("", response_model=list[MemberOut])
async def list_members(p: CurrentPrincipal, db: DB) -> list[MemberOut]:
    rows = await db.execute(
        select(WorkspaceMember, User)
        .join(User, User.id == WorkspaceMember.user_id)
        .where(WorkspaceMember.workspace_id == p.workspace_id, User.deleted_at.is_(None))
        .order_by(User.email)
    )
    return [MemberOut(user=UserOut.model_validate(u), role=Role(m.role)) for m, u in rows.all()]


@users_router.post("", response_model=MemberOut, status_code=201, dependencies=[require_role(Role.ADMIN)])
async def create_user(body: UserCreate, p: CurrentPrincipal, db: DB) -> MemberOut:
    if body.role == Role.OWNER and p.role != Role.OWNER:
        raise Conflict("Only owners can create owners")
    if await db.scalar(select(User.id).where(func.lower(User.email) == body.email.lower())):
        raise Conflict("A user with this email already exists")
    user = User(email=body.email.lower(), password_hash=hash_password(body.password), full_name=body.full_name)
    db.add(user)
    await db.flush()
    db.add(WorkspaceMember(workspace_id=p.workspace_id, user_id=user.id, role=body.role))
    await audit(db, p, "user.created", "user", user.id, {"email": user.email, "role": body.role})
    await db.commit()
    return MemberOut(user=UserOut.model_validate(user), role=body.role)


@users_router.patch("/{user_id}", response_model=MemberOut, dependencies=[require_role(Role.ADMIN)])
async def update_user(user_id: uuid.UUID, body: MemberUpdate, p: CurrentPrincipal, db: DB) -> MemberOut:
    member = await db.scalar(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == p.workspace_id, WorkspaceMember.user_id == user_id
        )
    )
    if member is None:
        raise NotFound("User not found in this workspace")
    user = await db.get(User, member.user_id)
    # Only owners may touch an owner at all (role, active flag or name), or make someone an owner.
    if member.role == Role.OWNER and p.role != Role.OWNER:
        raise Conflict("Only owners can change owner accounts")
    if body.role is not None:
        if body.role == Role.OWNER and p.role != Role.OWNER:
            raise Conflict("Only owners can change owner roles")
        member.role = body.role
    if body.is_active is not None:
        if user.id == p.user.id and not body.is_active:
            raise Conflict("You cannot deactivate yourself")
        user.is_active = body.is_active
    if body.full_name is not None:
        user.full_name = body.full_name
    await audit(db, p, "user.updated", "user", user.id, body.model_dump(exclude_none=True))
    await db.commit()
    return MemberOut(user=UserOut.model_validate(user), role=Role(member.role))
