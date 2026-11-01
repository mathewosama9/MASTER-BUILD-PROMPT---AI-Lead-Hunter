import logging

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address
from sqlalchemy import text

from app.api.v1 import (
    admin,
    admin_insights,
    auth,
    billing,
    campaigns,
    dashboard,
    exports,
    leads,
    profile,
    providers,
    public,
    reviews,
    settings,
    telegram,
)
from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.core.errors import register_error_handlers
from app.core.logging import configure_logging
from app.core.redis import async_redis

log = logging.getLogger(__name__)


def create_app() -> FastAPI:
    s = get_settings()
    configure_logging(s.log_level)
    app = FastAPI(
        title="Rasd API",
        version="0.1.0",
        description="B2B lead discovery, enrichment, AI analysis and scoring. All endpoints are under /api/v1.",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )
    limiter = Limiter(
        key_func=get_remote_address,
        default_limits=[s.rate_limit_default],
        storage_uri=s.redis_url if s.environment != "test" else "memory://",
        enabled=s.environment != "test",
    )
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=s.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Content-Type", "X-CSRF-Token", "Authorization"],
    )
    register_error_handlers(app)

    @app.middleware("http")
    async def security_headers(request, call_next):  # noqa: ANN001, ANN202
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        return response

    api = APIRouter(prefix="/api/v1")
    for r in (
        auth.router,
        auth.users_router,
        dashboard.router,
        campaigns.router,
        leads.router,
        leads.contacts_router,
        leads.suppression_router,
        exports.router,
        providers.router,
        telegram.router,
        settings.router,
        profile.router,
        public.router,
        billing.router,
        admin.router,
        admin_insights.router,
        reviews.router,
    ):
        api.include_router(r)
    # Aliases matching the documented endpoint groups.
    businesses = APIRouter(prefix="/businesses", tags=["leads"])
    businesses.add_api_route("/{lead_id}", leads.lead_detail, methods=["GET"])
    api.include_router(businesses)
    integrations = APIRouter(prefix="/integrations", tags=["providers"])
    integrations.add_api_route("", providers.list_providers, methods=["GET"])
    api.include_router(integrations)
    workspaces = APIRouter(prefix="/workspaces", tags=["settings"])
    workspaces.add_api_route("/current", settings.get_workspace_settings, methods=["GET"])
    api.include_router(workspaces)
    analysis = APIRouter(prefix="/analysis", tags=["leads"])
    analysis.add_api_route("/{lead_id}/run", leads.reanalyze, methods=["POST"])
    api.include_router(analysis)

    @api.get("/health", tags=["health"])
    async def health() -> dict:
        checks = {"api": "ok"}
        try:
            async with get_sessionmaker()() as db:
                await db.execute(text("SELECT 1"))
            checks["database"] = "ok"
        except Exception as exc:  # noqa: BLE001
            checks["database"] = f"error: {type(exc).__name__}"
        try:
            r = async_redis()
            await r.ping()
            await r.aclose()
            checks["redis"] = "ok"
        except Exception as exc:  # noqa: BLE001
            checks["redis"] = f"error: {type(exc).__name__}"
        healthy = all(v == "ok" for v in checks.values())
        return {
            "status": "ok" if healthy else "degraded",
            "checks": checks,
            "demo_mode": s.demo_mode,
            "version": app.version,
        }

    app.include_router(api)
    return app


app = create_app()
