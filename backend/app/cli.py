"""Operational commands.

python -m app.cli create-admin --email admin@example.com --password '...' --workspace "My Agency"
python -m app.cli run-demo --email admin@example.com          # runs a full demo campaign inline
python -m app.cli set-superuser --email you@example.com [--revoke]   # platform admin (/app/admin)
"""

import asyncio
import re
import uuid

import typer
from sqlalchemy import func, select

from app.core.db import worker_session
from app.core.security import hash_password
from app.models import User, Workspace, WorkspaceMember
from app.models.enums import Role

cli = typer.Typer(no_args_is_help=True)


async def _create_admin(email: str, password: str, workspace: str, full_name: str) -> None:
    async with worker_session() as db:
        user = await db.scalar(select(User).where(func.lower(User.email) == email.lower()))
        if user is None:
            user = User(
                email=email.lower(), password_hash=hash_password(password), full_name=full_name, is_superuser=True
            )
            db.add(user)
            await db.flush()
            typer.echo(f"Created user {email}")
        else:
            user.password_hash = hash_password(password)
            typer.echo(f"User {email} exists; password reset")
        member = await db.scalar(select(WorkspaceMember).where(WorkspaceMember.user_id == user.id))
        if member is None:
            slug = re.sub(r"[^a-z0-9]+", "-", workspace.lower()).strip("-") or "workspace"
            if await db.scalar(select(Workspace.id).where(Workspace.slug == slug)):
                slug = f"{slug}-{uuid.uuid4().hex[:6]}"
            ws = Workspace(name=workspace, slug=slug, settings={})
            db.add(ws)
            await db.flush()
            db.add(WorkspaceMember(workspace_id=ws.id, user_id=user.id, role=Role.OWNER))
            typer.echo(f"Created workspace '{workspace}' with {email} as owner")
        await db.commit()


@cli.command("create-admin")
def create_admin(
    email: str = typer.Option(...),
    password: str = typer.Option(..., prompt=True, hide_input=True),
    workspace: str = typer.Option("My Workspace"),
    full_name: str = typer.Option("Administrator"),
) -> None:
    if len(password) < 10:
        raise typer.BadParameter("Password must be at least 10 characters")
    asyncio.run(_create_admin(email, password, workspace, full_name))


async def _run_demo(email: str, target: int) -> None:
    from app.research.pipeline import execute_campaign, start_new_run
    from app.schemas.campaign import CampaignCreate, ResearchSettings, SourceIn
    from app.services.campaigns import create_campaign

    async with worker_session() as db:
        user = await db.scalar(select(User).where(func.lower(User.email) == email.lower()))
        if user is None:
            raise typer.BadParameter("Unknown user")
        member = await db.scalar(select(WorkspaceMember).where(WorkspaceMember.user_id == user.id))
        c = await create_campaign(
            db,
            member.workspace_id,
            user.id,
            CampaignCreate(
                name="Riyadh Dental Clinics (Demo)",
                country="SA",
                city="Riyadh",
                industry="dental_clinics",
                services=["appointment_automation", "whatsapp_automation"],
                sources=[SourceIn(provider_key="demo")],
                settings=ResearchSettings(target_count=target, max_companies=target + 5, email_verification=True),
            ),
            origin="api",
        )
        run = await start_new_run(db, c)
        await db.commit()
        status = await execute_campaign(db, c.id, run.id)
        await db.refresh(c)
        typer.echo(f"Campaign {c.id} finished: {status}")
        for k, v in (c.stats or {}).items():
            typer.echo(f"  {k}: {v}")


@cli.command("run-demo")
def run_demo(email: str = typer.Option(...), target: int = typer.Option(15)) -> None:
    asyncio.run(_run_demo(email, target))


async def _set_superuser(email: str, value: bool) -> None:
    async with worker_session() as db:
        user = await db.scalar(select(User).where(func.lower(User.email) == email.lower()))
        if user is None:
            raise typer.BadParameter(f"Unknown user {email}")
        user.is_superuser = value
        await db.commit()
        typer.echo(f"{email}: platform admin {'granted' if value else 'revoked'}")


@cli.command("set-superuser")
def set_superuser(email: str = typer.Option(...), revoke: bool = typer.Option(False, "--revoke")) -> None:
    asyncio.run(_set_superuser(email, not revoke))


if __name__ == "__main__":
    cli()
