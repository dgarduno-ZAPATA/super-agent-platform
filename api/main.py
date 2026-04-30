import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

import sentry_sdk
import structlog
from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.logging import LoggingIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from adapters.storage.db import session_scope
from adapters.storage.models import AdminUserModel
from api.dependencies import get_current_user, get_inventory_provider
from api.middleware.correlation import CorrelationMiddleware
from api.routers.admin_panel import router as admin_router
from api.routers.auth import router as auth_router
from api.routers.campaigns import router as campaigns_router
from api.routers.conversations import router as conversations_router
from api.routers.dashboard import router as dashboard_router
from api.routers.knowledge import router as knowledge_router
from api.routers.leads import router as leads_router
from api.routers.webhook import router as webhook_router
from core.brand.loader import BrandValidationError, load_brand_config
from core.config import get_settings
from core.observability.logging import setup_logging
from core.ports.inventory_provider import InventoryProvider
from infra.scheduler import start_campaign_scheduler, stop_campaign_scheduler

SERVICE_NAME = "super-agent-platform"


async def _check_admin_users(session: AsyncSession, logger: structlog.BoundLogger) -> int:
    result = await session.execute(
        select(func.count()).select_from(AdminUserModel).where(AdminUserModel.is_active.is_(True))
    )
    active_count = int(result.scalar() or 0)
    if active_count == 0:
        logger.warning(
            "no_active_admin_users",
            hint="Run: docker compose exec app python scripts/migrate_admin_user.py",
        )
    else:
        logger.info("admin_users_ok", active_count=active_count)
    return active_count


def create_app() -> FastAPI:
    settings = get_settings()
    setup_logging(settings.log_level)
    logger = structlog.get_logger("super_agent_platform.api")

    sentry_logging = LoggingIntegration(
        level=logging.WARNING,
        event_level=logging.ERROR,
    )
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        integrations=[
            FastApiIntegration(),
            StarletteIntegration(),
            sentry_logging,
        ],
        traces_sample_rate=0.1,
        environment=settings.environment,
        release=settings.app_version,
    )
    if settings.sentry_dsn.strip():
        sentry_sdk.capture_message("sentry_initialized_super_agent_platform", level="info")

    app = FastAPI(title="Super Agent Platform")
    app.add_middleware(CorrelationMiddleware)

    @app.middleware("http")
    async def security_headers_middleware(request: Request, call_next):  # type: ignore[no-untyped-def]
        response = await call_next(request)
        path = request.url.path
        if path.startswith("/admin"):
            csp = (
                "default-src 'self'; "
                "style-src 'self' 'unsafe-inline'; "
                "script-src 'self' 'unsafe-inline'; "
                "img-src 'self' data:; "
                "connect-src 'self'; "
                "font-src 'self'"
            )
        else:
            csp = "default-src 'none'"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = csp
        return response

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        try:
            brand = load_brand_config()
        except BrandValidationError:
            logger.exception(
                "brand_validation_failed",
                service=SERVICE_NAME,
                app_env=settings.app_env,
                brand_path=str(settings.brand_path),
            )
            raise

        try:
            async with session_scope() as session:
                await _check_admin_users(session=session, logger=logger)
        except Exception as exc:
            logger.warning(
                "admin_users_check_failed",
                error=str(exc),
                hint="run alembic upgrade head before enabling DB-backed admin auth",
            )

        if (
            not settings.jwt_secret_key.strip()
            or not settings.internal_token.strip()
            or not settings.evolution_api_key.strip()
        ):
            logger.critical(
                "security_configuration_invalid",
                jwt_secret_key_set=bool(settings.jwt_secret_key.strip()),
                internal_token_set=bool(settings.internal_token.strip()),
                evolution_api_key_set=bool(settings.evolution_api_key.strip()),
            )
            raise RuntimeError(
                "JWT_SECRET_KEY, INTERNAL_TOKEN and EVOLUTION_API_KEY must be configured"
            )

        application.state.brand = brand
        scheduler = start_campaign_scheduler(application, settings)
        application.state.campaign_scheduler = scheduler
        logger.info(
            "app_started",
            service=SERVICE_NAME,
            app_env=settings.app_env,
            brand_path=str(settings.brand_path),
            brand_name=brand.brand.display_name,
            fsm_states=len(brand.fsm.states),
            fsm_initial_state=brand.fsm.initial_state,
        )
        yield
        stop_campaign_scheduler(getattr(application.state, "campaign_scheduler", None))
        logger.info("app_stopped", service=SERVICE_NAME)

    app.router.lifespan_context = lifespan
    app.include_router(webhook_router)
    app.include_router(auth_router)
    app.include_router(conversations_router)
    app.include_router(dashboard_router)
    app.include_router(leads_router)
    app.include_router(campaigns_router)
    app.include_router(knowledge_router)
    app.include_router(admin_router)

    @app.get("/health")
    async def healthcheck(
        inventory_provider: Annotated[InventoryProvider, Depends(get_inventory_provider)],
    ) -> dict[str, object]:
        inventory_count = 0
        try:
            inventory_count = len(inventory_provider.get_products())
        except Exception as exc:
            logger.warning("healthcheck_inventory_count_failed", error=str(exc))

        logger.info(
            "healthcheck_requested",
            service=SERVICE_NAME,
            inventory_count=inventory_count,
        )
        logger.info(
            f"✅ Inventario cargado: {inventory_count} items",
            service=SERVICE_NAME,
            inventory_count=inventory_count,
            sheet_csv_url_set=bool(settings.inventory_sheet_url.strip()),
        )
        return {
            "status": "ok",
            "service": SERVICE_NAME,
            "inventory_count": inventory_count,
        }

    @app.get("/brand/info")
    async def brand_info() -> dict[str, str]:
        logger.info("brand_info_requested", service=SERVICE_NAME)
        return {"name": app.state.brand.brand.display_name}

    @app.get("/brand/config")
    async def brand_config(
        current_user: Annotated[dict[str, object], Depends(get_current_user)],
    ) -> dict[str, str]:
        del current_user
        brand = app.state.brand.brand
        return {
            "name": brand.name,
            "slug": brand.slug,
            "logo_url": brand.logo_url,
            "primary_color": brand.primary_color,
            "accent_color": brand.accent_color,
            "admin_title": brand.admin_title,
            "support_phone": brand.support_phone,
        }

    @app.get("/sentry-debug")
    async def sentry_debug(
        x_internal_token: Annotated[str | None, Header(alias="X-Internal-Token")] = None,
    ) -> dict[str, str]:
        if x_internal_token != settings.internal_token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="missing_or_invalid_internal_token",
            )
        raise RuntimeError("sentry_debug_triggered")

    return app


app = create_app()
