"""Credits ledger: every balance change goes through `_apply`, which updates the balance atomically and writes the
ledger row in the same transaction. Callers commit.

Charging rule (what a "contact" is): a business new to the workspace (`CampaignLead.pre_existing` is false) that a
non-demo campaign delivered with at least one usable phone, WhatsApp or email (not invalid, not suppressed).
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import exists, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models import BusinessContact, CreditTransaction, PlatformSettings, User, Workspace, WorkspaceMember
from app.models.enums import ApprovalStatus, ContactType, CreditKind, Role, VerificationStatus

USABLE_CONTACT_TYPES = (ContactType.PHONE, ContactType.WHATSAPP, ContactType.EMAIL)
LOW_BALANCE_CREDITS = 10  # below this the dashboard asks the client to top up


class InsufficientCredits(AppError):
    status_code = 402

    def __init__(self, message: str = "Not enough credits") -> None:
        super().__init__(message, code="insufficient_credits")


class EmailUnverified(AppError):
    status_code = 403

    def __init__(self) -> None:
        super().__init__("Confirm your email to activate your free trial credits", code="email_unverified")


class AccountPending(AppError):
    status_code = 403

    def __init__(self) -> None:
        super().__init__(
            "Your account is being reviewed; the free trial starts once it is approved", code="account_pending"
        )


class TrialExpired(AppError):
    status_code = 402

    def __init__(self) -> None:
        super().__init__("Your free trial has ended; top up credits to continue", code="trial_expired")


async def platform_settings(db: AsyncSession) -> PlatformSettings:
    row = await db.get(PlatformSettings, 1)
    if row is None:
        row = PlatformSettings(id=1, payment_instructions_ar="", payment_instructions_en="")
        db.add(row)
        await db.flush()
    return row


async def _apply(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    delta: int,
    kind: CreditKind,
    *,
    campaign_id: uuid.UUID | None = None,
    business_id: uuid.UUID | None = None,
    note: str | None = None,
    created_by: uuid.UUID | None = None,
) -> CreditTransaction:
    # One statement: concurrent callers serialise on the row lock and re-check the condition, so the balance never
    # goes below zero however many campaigns charge at once.
    balance = await db.scalar(
        update(Workspace)
        .where(Workspace.id == workspace_id, Workspace.credit_balance + delta >= 0)
        .values(credit_balance=Workspace.credit_balance + delta)
        .returning(Workspace.credit_balance)
        .execution_options(synchronize_session="fetch")
    )
    if balance is None:
        raise InsufficientCredits()
    tx = CreditTransaction(
        workspace_id=workspace_id,
        delta=delta,
        balance_after=balance,
        kind=kind,
        campaign_id=campaign_id,
        business_id=business_id,
        note=note,
        created_by=created_by,
    )
    db.add(tx)
    await db.flush()
    return tx


async def grant(
    db: AsyncSession, workspace_id: uuid.UUID, amount: int, kind: CreditKind, **kw: object
) -> CreditTransaction:
    if amount <= 0:
        raise ValueError("grant amount must be positive")
    return await _apply(db, workspace_id, amount, kind, **kw)  # type: ignore[arg-type]


async def charge(
    db: AsyncSession, workspace_id: uuid.UUID, amount: int, kind: CreditKind = CreditKind.CAMPAIGN_CHARGE, **kw: object
) -> CreditTransaction:
    """Spend `amount` credits; raises InsufficientCredits (and changes nothing) if the balance is too low."""
    if amount <= 0:
        raise ValueError("charge amount must be positive")
    tx = await _apply(db, workspace_id, -amount, kind, **kw)  # type: ignore[arg-type]
    if 0 < tx.balance_after < LOW_BALANCE_CREDITS <= tx.balance_after + amount:  # just crossed the line: tell once
        from app.services.notify import notify

        await notify(
            db, "credits_low", workspace_id=workspace_id, params={"balance": tx.balance_after}, link="/app/billing"
        )
    return tx


async def adjust(db: AsyncSession, workspace_id: uuid.UUID, delta: int, **kw: object) -> CreditTransaction:
    """Admin correction in either direction (never below zero)."""
    if delta == 0:
        raise ValueError("adjustment must not be zero")
    return await _apply(db, workspace_id, delta, CreditKind.MANUAL_ADJUST, **kw)  # type: ignore[arg-type]


async def start_trial(db: AsyncSession, workspace: Workspace, created_by: uuid.UUID | None = None) -> None:
    """Free trial for a new self-signup workspace, from the admin-editable platform settings."""
    s = await platform_settings(db)
    workspace.trial_ends_at = datetime.now(UTC) + timedelta(days=max(0, s.trial_days))
    await db.flush()
    if s.trial_credits > 0:
        await grant(db, workspace.id, s.trial_credits, CreditKind.TRIAL_GRANT, note="Free trial", created_by=created_by)


async def on_trial(db: AsyncSession, workspace: Workspace) -> bool:
    """A workspace is on trial until its first approved purchase."""
    if workspace.trial_ends_at is None:
        return False
    purchased = await db.scalar(
        select(
            exists().where(
                CreditTransaction.workspace_id == workspace.id, CreditTransaction.kind == CreditKind.PURCHASE
            )
        )
    )
    return not purchased


async def owner_verified(db: AsyncSession, workspace_id: uuid.UUID) -> bool:
    """Has any owner of the workspace confirmed their email?"""
    return bool(
        await db.scalar(
            select(
                exists().where(
                    WorkspaceMember.workspace_id == workspace_id,
                    WorkspaceMember.role == Role.OWNER,
                    WorkspaceMember.user_id == User.id,
                    User.email_verified_at.is_not(None),
                )
            )
        )
    )


async def owner_approved(db: AsyncSession, workspace_id: uuid.UUID) -> bool:
    """Has the platform admin approved any owner of the workspace?"""
    return bool(
        await db.scalar(
            select(
                exists().where(
                    WorkspaceMember.workspace_id == workspace_id,
                    WorkspaceMember.role == Role.OWNER,
                    WorkspaceMember.user_id == User.id,
                    User.approval_status == ApprovalStatus.APPROVED,
                )
            )
        )
    )


async def awaiting_approval(db: AsyncSession, workspace: Workspace) -> bool:
    """A self-signup whose free trial waits for the platform admin's approval."""
    return (
        not workspace.billing_exempt and workspace.trial_ends_at is None and not await owner_approved(db, workspace.id)
    )


async def awaiting_verification(db: AsyncSession, workspace: Workspace) -> bool:
    """A self-signup whose free trial starts once an owner confirms their email."""
    return (
        not workspace.billing_exempt and workspace.trial_ends_at is None and not await owner_verified(db, workspace.id)
    )


async def ensure_can_spend(db: AsyncSession, workspace: Workspace) -> None:
    """Gate for starting paid work: a positive balance, and an unexpired trial while still on trial."""
    if workspace.suspended_at is not None:
        raise AppError("This workspace is suspended. Contact support.", status_code=403, code="workspace_suspended")
    if workspace.billing_exempt:
        return
    if await on_trial(db, workspace) and workspace.trial_ends_at <= datetime.now(UTC):
        raise TrialExpired()
    if workspace.credit_balance <= 0:
        if await awaiting_verification(db, workspace):
            raise EmailUnverified()
        if await awaiting_approval(db, workspace):
            raise AccountPending()
        raise InsufficientCredits("You have no credits left; top up to run a campaign")


async def has_usable_contact(db: AsyncSession, business_id: uuid.UUID) -> bool:
    return bool(
        await db.scalar(
            select(
                exists().where(
                    BusinessContact.business_id == business_id,
                    BusinessContact.type.in_(USABLE_CONTACT_TYPES),
                    BusinessContact.verification_status != VerificationStatus.INVALID,
                    BusinessContact.is_suppressed.is_(False),
                )
            )
        )
    )
