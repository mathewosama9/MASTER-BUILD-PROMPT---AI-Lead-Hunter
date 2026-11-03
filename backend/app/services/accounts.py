"""Account emails (password reset, email confirmation) and what confirming an email unlocks.

Both links carry signed, expiring tokens (see core/security.py), not database rows:
- reset: bound to the current password hash, so it works once and dies when the password changes;
- verify: bound to the email address it was sent to.
"""

import logging
import uuid
from datetime import UTC, datetime
from urllib.parse import quote

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.core.security import create_purpose_token, decode_purpose_token, password_fingerprint
from app.models import User, Workspace, WorkspaceMember
from app.models.enums import ApprovalStatus, Role
from app.services import credits as credit_svc
from app.services.mailer import send_email
from app.services.notify.templates import email_layout

log = logging.getLogger(__name__)

RESET = "password-reset"
VERIFY = "email-verify"

_TEXT = {
    "reset": {
        "en": {
            "subject": "Reset your Rasd password",
            "intro": "Someone (hopefully you) asked to reset the password for {email}.",
            "action": "Choose a new password",
            "outro": "The link works once and expires in {minutes} minutes. If you didn't ask for this, ignore this "
            "email; your password stays the same.",
        },
        "ar": {
            "subject": "إعادة تعيين كلمة مرور رصد",
            "intro": "وصلنا طلب لإعادة تعيين كلمة المرور للحساب {email}.",
            "action": "اختر كلمة مرور جديدة",
            "outro": "الرابط يعمل مرة واحدة وينتهي خلال {minutes} دقيقة. إذا لم تطلب ذلك فتجاهل هذه الرسالة، "
            "وستبقى كلمة المرور كما هي.",
        },
    },
    "verify": {
        "en": {
            "subject": "Confirm your email for Rasd",
            "intro": "Welcome, {name}. Confirm {email} to activate your account and your free trial credits.",
            # A signup waiting for the platform admin: say so, so nobody waits for credits after confirming.
            "intro_pending": "Welcome, {name}. We received your sign-up and our team is reviewing it (we keep one "
            "free trial per person). Confirm {email} now; your free trial credits are added as soon as the account "
            "is approved, and we'll email you then.",
            "action": "Confirm my email",
            "outro": "The link expires in {hours} hours. If you didn't create an account, ignore this email.",
        },
        "ar": {
            "subject": "أكّد بريدك الإلكتروني في رصد",
            "intro": "أهلاً {name}. أكّد البريد {email} لتفعيل حسابك ورصيد التجربة المجانية.",
            "intro_pending": "أهلاً {name}. استلمنا طلب تسجيلك وفريقنا يراجعه الآن (التجربة المجانية مرة واحدة لكل "
            "شخص). أكّد البريد {email} الآن، وتُضاف نقاط التجربة فور الموافقة على الحساب، وسنراسلك وقتها.",
            "action": "تأكيد البريد",
            "outro": "ينتهي الرابط خلال {hours} ساعة. إذا لم تنشئ حساباً فتجاهل هذه الرسالة.",
        },
    },
}


def _render(kind: str, user: User, link: str) -> tuple[str, str, str]:
    s = get_settings()
    lang = "ar" if user.locale == "ar" else "en"
    t = _TEXT[kind][lang]
    values = {
        "email": user.email,
        "name": user.full_name or user.email,
        "minutes": s.password_reset_minutes,
        "hours": s.email_verify_hours,
    }
    intro_key = "intro_pending" if kind == "verify" and user.approval_status == ApprovalStatus.PENDING else "intro"
    intro, outro = t[intro_key].format(**values), t["outro"].format(**values)
    text = f"{intro}\n\n{t['action']}:\n{link}\n\n{outro}\n\nرصد · Rasd"
    body = email_layout(lang, intro, action=t["action"], link=link, outro=outro)
    return t["subject"], text, body


def reset_link(user: User) -> str:
    s = get_settings()
    token = create_purpose_token(RESET, user.id, s.password_reset_minutes, pv=password_fingerprint(user.password_hash))
    return f"{s.frontend_url.rstrip('/')}/reset-password?token={quote(token)}"


def verify_link(user: User) -> str:
    s = get_settings()
    token = create_purpose_token(VERIFY, user.id, s.email_verify_hours * 60, email=user.email.lower())
    return f"{s.frontend_url.rstrip('/')}/verify-email?token={quote(token)}"


def decode_reset(token: str) -> dict | None:
    return decode_purpose_token(RESET, token)


def decode_verify(token: str) -> dict | None:
    return decode_purpose_token(VERIFY, token)


async def _send(kind: str, user_id: uuid.UUID) -> None:
    # Runs after the response (BackgroundTasks) with its own session, so the reply time says nothing about whether
    # the account exists.
    async with get_sessionmaker()() as db:
        user = await db.get(User, user_id)
        if user is None or not user.is_active or user.deleted_at is not None:
            return
        link = reset_link(user) if kind == "reset" else verify_link(user)
        subject, text, body = _render(kind, user, link)
    await send_email(user.email, subject, text, body)


async def send_password_reset(user_id: uuid.UUID) -> None:
    await _send("reset", user_id)


async def send_verification(user_id: uuid.UUID) -> None:
    await _send("verify", user_id)


async def mark_verified(db: AsyncSession, user: User) -> bool:
    """Confirm the user's email (caller holds the user row lock and commits). Once the admin has also approved the
    account, the first confirmation starts the free trial. Returns False if already done."""
    if user.email_verified_at is not None:
        return False
    user.email_verified_at = datetime.now(UTC)
    if user.approval_status == ApprovalStatus.APPROVED:
        await start_owner_trials(db, user)
    return True


async def start_owner_trials(db: AsyncSession, user: User) -> None:
    """Start the free trial of each self-signup workspace the user owns that hasn't had one. A trial needs both a
    confirmed email and an approved account; whichever comes last calls this."""
    workspaces = await db.scalars(
        select(Workspace)
        .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
        .where(
            WorkspaceMember.user_id == user.id,
            WorkspaceMember.role == Role.OWNER,
            Workspace.trial_ends_at.is_(None),
            Workspace.billing_exempt.is_(False),
            Workspace.deleted_at.is_(None),
        )
        .with_for_update(of=Workspace)
    )
    for ws in workspaces.all():
        await credit_svc.start_trial(db, ws, created_by=user.id)
