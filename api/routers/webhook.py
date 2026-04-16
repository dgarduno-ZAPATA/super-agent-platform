from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, Request, Response, status

from api.dependencies import get_inbound_message_handler
from core.observability.context import get_context
from core.services.inbound_handler import InboundMessageHandler

logger = structlog.get_logger("super_agent_platform.api.webhook")

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/whatsapp", status_code=status.HTTP_200_OK)
async def receive_whatsapp_webhook(
    payload: dict[str, object],
    request: Request,
    handler: Annotated[InboundMessageHandler, Depends(get_inbound_message_handler)],
) -> Response:
    try:
        result = await handler.handle(payload)
        logger.info(
            "whatsapp_webhook_received",
            correlation_id=get_context().get("request_id"),
            path=request.url.path,
            processing_status=result.status,
            processed=result.processed,
        )
    except Exception:
        logger.exception(
            "whatsapp_webhook_processing_failed",
            correlation_id=get_context().get("request_id"),
            path=request.url.path,
        )

    return Response(status_code=status.HTTP_200_OK)
