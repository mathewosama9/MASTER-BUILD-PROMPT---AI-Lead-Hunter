import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Request, Response
from sqlalchemy import func, select

from app.api.deps import CSRF_COOKIE, DB, SESSION_COOKIE, CurrentPrincipal, audit, require_role
from app.core.config import get_settings
from app.core.errors import Conflict, NotFound, Unauthorized
from app.core.security import create_access_token, hash_password, new_csrf_token, verify_password
from app.models import AuditLog, User, Workspace, WorkspaceMember
from app.models.enums import Role
from app.schemas.auth import LoginIn, MemberOut, MemberUpdate, MeOut, PasswordChange, UserCreate, UserOut
from app.schemas.common import Message

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
    user.last_login_at = datetime.now(UTC)
    token = create_access_token(user.id, member.workspace_id)
    csrf = new_csrf_token()
    _set_session(response, token, csrf)
    db.add(
        AuditLog(
            workspace_id=member.workspace_id,
            user_id=user.id,
            action="auth.login",
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
async def change_password(body: PasswordChange, p: CurrentPrincipal, db: DB) -> Message:
    if not verify_password(body.current_password, p.user.password_hash):
        raise Unauthorized("Current password is incorrect")
    p.user.password_hash = hash_password(body.new_password)
    await audit(db, p, "auth.password_changed", "user", p.user.id)
    await db.commit()
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
    if body.role is not None:
        if (body.role == Role.OWNER or member.role == Role.OWNER) and p.role != Role.OWNER:
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
