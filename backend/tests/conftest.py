"""Test setup.

Uses PostgreSQL when TEST_DATABASE_URL is set (recommended; CI and docker-compose do this), otherwise an
in-process SQLite database so unit tests run anywhere. Redis is optional: event fan-out is best-effort.
"""

import os
import uuid

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("DEMO_MODE", "true")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-unit-tests-only")
os.environ.setdefault("TELEGRAM_SERVICE_TOKEN", "test-service-token")
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", "sqlite+aiosqlite:///./test.db")
os.environ.setdefault("REDIS_URL", os.environ.get("TEST_REDIS_URL", "redis://localhost:1/0"))
for key in (
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "BRAVE_API_KEY",
    "HUNTER_API_KEY",
    "X_BEARER_TOKEN",
    "TELEGRAM_BOT_TOKEN",
):
    os.environ.pop(key, None)

import httpx  # noqa: E402
import pytest  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.db import get_engine, get_sessionmaker, reset_engine  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.models import Base, User, Workspace, WorkspaceMember  # noqa: E402
from app.models.enums import Role  # noqa: E402

get_settings.cache_clear()
PASSWORD = "Sup3r-Secret-Pass"


@pytest.fixture(scope="session", autouse=True)
async def _schema():
    reset_engine()
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
async def db():
    async with get_sessionmaker()() as session:
        yield session


@pytest.fixture
def dispatched(monkeypatch):
    """Capture Celery dispatches instead of sending them to a broker."""
    calls: list[tuple[uuid.UUID, uuid.UUID]] = []

    def fake_dispatch(campaign_id, run_id):
        calls.append((campaign_id, run_id))
        return f"task-{len(calls)}"

    monkeypatch.setattr("app.services.campaigns.dispatch_run", fake_dispatch)
    return calls


async def make_user(db, *, role: Role = Role.OWNER, workspace: Workspace | None = None) -> tuple[User, Workspace]:
    if workspace is None:
        workspace = Workspace(name=f"WS {uuid.uuid4().hex[:6]}", slug=f"ws-{uuid.uuid4().hex[:10]}", settings={})
        db.add(workspace)
        await db.flush()
    user = User(
        email=f"user-{uuid.uuid4().hex[:8]}@example.com", password_hash=hash_password(PASSWORD), full_name="Test User"
    )
    db.add(user)
    await db.flush()
    db.add(WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role=role))
    await db.commit()
    return user, workspace


@pytest.fixture
def app():
    from app.main import create_app

    return create_app()


async def login(app, email: str) -> httpx.AsyncClient:
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    r = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    client.headers["x-csrf-token"] = r.json()["csrf_token"]
    return client


@pytest.fixture
async def owner(db):
    return await make_user(db)


@pytest.fixture
async def client(app, owner):
    c = await login(app, owner[0].email)
    yield c
    await c.aclose()


async def run_latest(campaign_id: str) -> str:
    """Execute the most recently queued run inline (what the Celery worker would do)."""
    from app.models import CampaignRun
    from app.research.pipeline import execute_campaign

    async with get_sessionmaker()() as s:
        run = await s.scalar(
            select(CampaignRun)
            .where(CampaignRun.campaign_id == uuid.UUID(campaign_id))
            .order_by(CampaignRun.run_number.desc())
            .limit(1)
        )
        status = await execute_campaign(s, uuid.UUID(campaign_id), run.id)
        return status.value if status else ""
