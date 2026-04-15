from __future__ import annotations

from uuid import uuid4

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.base import RequestResponseEndpoint

from core.observability.context import bind_context, clear_context
from core.observability.logging import REQUEST_ID_HEADER


class CorrelationMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        clear_context()

        request_id = str(uuid4())
        bind_context(
            request_id=request_id,
            conversation_id=request.headers.get("X-Conversation-ID"),
            lead_id=request.headers.get("X-Lead-ID"),
            campaign_id=request.headers.get("X-Campaign-ID"),
            tenant_id=request.headers.get("X-Tenant-ID"),
        )

        try:
            response = await call_next(request)
        finally:
            clear_context()

        response.headers[REQUEST_ID_HEADER] = request_id
        return response
