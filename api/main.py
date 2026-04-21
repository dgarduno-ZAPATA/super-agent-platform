from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request

from api.routers.admin_panel import router as admin_router
from api.routers.auth import router as auth_router
from api.middleware.correlation import CorrelationMiddleware
from api.routers.campaigns import router as campaigns_router
from api.routers.conversations import router as conversations_router
from api.routers.dashboard import router as dashboard_router
from api.routers.leads import router as leads_router
from api.routers.webhook import router as webhook_router
from core.brand.loader import BrandValidationError, load_brand
from core.config import get_settings
from core.observability.logging import setup_logging
from infra.scheduler import start_campaign_scheduler, stop_campaign_scheduler

SERVICE_NAME = "super-agent-platform"


def create_app() -> FastAPI:
    settings = get_settings()
    setup_logging(settings.log_level)
    logger = structlog.get_logger("super_agent_platform.api")
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
            brand = load_brand(settings.brand_path)
        except BrandValidationError:
            logger.exception(
                "brand_validation_failed",
                service=SERVICE_NAME,
                app_env=settings.app_env,
                brand_path=str(settings.brand_path),
            )
            raise

        if (
            not settings.jwt_secret_key.strip()
            or not settings.admin_password.strip()
            or not settings.internal_token.strip()
            or not settings.evolution_api_key.strip()
        ):
            logger.critical(
                "security_configuration_invalid",
                jwt_secret_key_set=bool(settings.jwt_secret_key.strip()),
                admin_password_set=bool(settings.admin_password.strip()),
                internal_token_set=bool(settings.internal_token.strip()),
                evolution_api_key_set=bool(settings.evolution_api_key.strip()),
            )
            raise RuntimeError(
                "JWT_SECRET_KEY, ADMIN_PASSWORD, INTERNAL_TOKEN and EVOLUTION_API_KEY must be configured"
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
    app.include_router(admin_router)

    @app.get("/health")
    async def healthcheck() -> dict[str, str]:
        logger.info("healthcheck_requested", service=SERVICE_NAME)
        return {"status": "ok", "service": SERVICE_NAME}

    @app.get("/brand/info")
    async def brand_info() -> dict[str, str]:
        logger.info("brand_info_requested", service=SERVICE_NAME)
        return {"name": app.state.brand.brand.display_name}

    return app


app = create_app()
