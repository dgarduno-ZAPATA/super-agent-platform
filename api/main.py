from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from api.middleware.correlation import CorrelationMiddleware
from api.routers.conversations import router as conversations_router
from api.routers.dashboard import router as dashboard_router
from api.routers.webhook import router as webhook_router
from core.brand.loader import BrandValidationError, load_brand
from core.config import get_settings
from core.observability.logging import setup_logging

SERVICE_NAME = "super-agent-platform"


def create_app() -> FastAPI:
    settings = get_settings()
    setup_logging(settings.log_level)
    logger = structlog.get_logger("super_agent_platform.api")
    app = FastAPI(title="Super Agent Platform")
    app.add_middleware(CorrelationMiddleware)

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

        application.state.brand = brand
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
        logger.info("app_stopped", service=SERVICE_NAME)

    app.router.lifespan_context = lifespan
    app.include_router(webhook_router)
    app.include_router(conversations_router)
    app.include_router(dashboard_router)

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
