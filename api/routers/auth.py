from __future__ import annotations

from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from api.dependencies import get_audit_log_service, get_login_attempt_service
from core.auth.jwt_handler import create_access_token
from core.config import get_settings
from core.services.audit_log_service import AuditLogService
from core.services.login_attempt_service import LoginAttemptService

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

_ATTEMPTS_BY_IP: dict[str, deque[datetime]] = defaultdict(deque)
_MAX_ATTEMPTS_PER_MINUTE = 5
_WINDOW = timedelta(minutes=1)


class TokenRequest(BaseModel):
    username: str
    password: str


@router.post("/token", status_code=status.HTTP_200_OK)
async def issue_token(
    payload: TokenRequest,
    request: Request,
    audit_log_service: Annotated[AuditLogService, Depends(get_audit_log_service)],
    login_attempt_service: Annotated[LoginAttemptService, Depends(get_login_attempt_service)],
) -> dict[str, str]:
    client_host = request.client.host if request.client is not None else "unknown"
    user_agent = request.headers.get("user-agent")
    now = datetime.now(UTC)

    if await login_attempt_service.check_lockout(client_host):
        remaining = await login_attempt_service.get_remaining_lockout(client_host)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Demasiados intentos fallidos. Intenta en {remaining} minutos.",
        )

    attempts = _ATTEMPTS_BY_IP[client_host]
    while attempts and now - attempts[0] > _WINDOW:
        attempts.popleft()

    if len(attempts) >= _MAX_ATTEMPTS_PER_MINUTE:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="too_many_login_attempts",
        )

    settings = get_settings()
    if payload.username != settings.admin_username or payload.password != settings.admin_password:
        attempts.append(now)
        await login_attempt_service.record_attempt(
            ip=client_host,
            username=payload.username,
            success=False,
        )
        await audit_log_service.log(
            actor="admin",
            action="login_failed",
            details={"username": payload.username},
            ip_address=client_host,
            user_agent=user_agent,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid_credentials",
        )

    await login_attempt_service.record_attempt(
        ip=client_host,
        username=payload.username,
        success=True,
    )
    token = create_access_token({"sub": payload.username})
    await audit_log_service.log(
        actor="admin",
        action="login_success",
        details={"username": payload.username},
        ip_address=client_host,
        user_agent=user_agent,
    )
    return {"access_token": token, "token_type": "bearer"}
