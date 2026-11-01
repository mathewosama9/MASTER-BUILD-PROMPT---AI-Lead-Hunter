import re
import secrets
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Request, Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.api.deps import CSRF_COOKIE, DB, SESSION_COOKIE, CurrentPrincipal, audit, require_role
from app.core.config import get_settings
from app.core.errors import AppError, Conflict, NotFound, Unauthorized
from app.core.ratelimit import enforce
from app.core.security import (
    create_access_token,
    hash_password,
    new_csrf_token,
    password_fingerprint,
    verify_password,
)
from app.models import AuditLog, User, Workspace, WorkspaceMember
from app.models.enums import Role
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

router = APIRouter(prefix="/auth", tags=["auth"])
users_router = APIRouter(prefix="/users", tags=["users"])


def _set_session(response: Response, token: str, csrf: str) -> None:
    s = get_settings()
    common = {
        "secure": s.cookie_secure,
        "samesite": "lax",
        "domain": s.cookie_domain,
        "path": "/",
        "max_age": s.access_token_minutes * 60,
    }
    response.set_cookie(SESSION_COOKIE, token, httponly=True, **common)
    response.set_cookie(CSRF_COOKIE, csrf, httponly=False, **common)


@router.post("/login", response_model=MeOut)
async def login(body: LoginIn, request: Request, response: Response, db: DB) -> MeOut:
    user = await db.scalar(select(User).where(func.lower(User.email) == body.email.lower(), User.deleted_at.is_(None)))
    if user is None or not user.is_active or not verify_password(body.password, user.password_hash):
        raise Unauthorized("Invalid email or password")
    member = await db.scalar(
        select(WorkspaceMember).where(WorkspaceMember.user_id == user.id).order_by(WorkspaceMember.created_at).limit(1)
    )
    if member is None:
        raise Unauthorized("User has no workspace")
    return await _start_session(db, request, response, user, member, "auth.login")


async def _start_session(
    db: DB, request: Request, response: Response, user: User, member: WorkspaceMember, action: str
) -> MeOut:
    user.last_login_at = datetime.now(UTC)
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
    await db.commit()
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


def _ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@router.post("/register", response_model=MeOut, status_code=201)
async def register(
    body: RegisterIn, request: Request, response: Response, background: BackgroundTasks, db: DB
) -> MeOut:
    """Self-signup: a new workspace owned by the caller. The free trial (from the platform settings) starts when the
    owner confirms their email, so one inbox gets one trial."""
    await enforce(f"signup:{_ip(request)}", get_settings().signup_limit_per_hour, 3600)
    email = body.email.lower()
    if await db.scalar(select(User.id).where(func.lower(User.email) == email)):
        raise Conflict("An account with this email already exists; sign in instead", code="email_taken")
    user = User(
        email=email,
        password_hash=hash_password(body.password),
        full_name=body.full_name,
        phone=body.phone,
        locale=body.locale,
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
    me = await _start_session(db, request, response, user, member, "auth.registered")
    background.add_task(accounts.send_verification, user.id)
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
    await accounts.mark_verified(db, user)  # the reset link proves the user reads this inbox
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
    return Message(message="Logged out")


@router.get("/me", response_model=MeOut)
async def me(p: CurrentPrincipal, request: Request, db: DB) -> MeOut:
    ws = await db.get(Workspace, p.workspace_id)
    return MeOut(
        user=UserOut.model_validate(p.user),
        workspace_id=p.workspace_id,
        workspace_name=ws.name if ws else "",
        role=p.role,
        csrf_token=request.cookies.get(CSRF_COOKIE),
        demo_mode=get_settings().demo_mode,
    )


@router.post("/password", response_model=Message)
async def change_password(
    body: PasswordChange, p: CurrentPrincipal, request: Request, response: Response, db: DB
) -> Message:
    if not verify_password(body.current_password, p.user.password_hash):
        raise Unauthorized("Current password is incorrect")
    p.user.password_hash = hash_password(body.new_password)  # signs out other sessions
    await audit(db, p, "auth.password_changed", "user", p.user.id)
    await db.commit()
    if p.via == "web":  # keep this browser signed in
        token = create_access_token(p.user.id, p.workspace_id, password_hash=p.user.password_hash)
        _set_session(response, token, request.cookies.get(CSRF_COOKIE) or new_csrf_token())
    return Message(message="Password updated")


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
