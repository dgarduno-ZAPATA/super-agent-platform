from __future__ import annotations

from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel

from core.auth.jwt_handler import create_access_token
from core.config import get_settings

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

_ATTEMPTS_BY_IP: dict[str, deque[datetime]] = defaultdict(deque)
_MAX_ATTEMPTS_PER_MINUTE = 5
_WINDOW = timedelta(minutes=1)


class TokenRequest(BaseModel):
    username: str
    password: str


@router.post("/token", status_code=status.HTTP_200_OK)
async def issue_token(payload: TokenRequest, request: Request) -> dict[str, str]:
    client_host = request.client.host if request.client is not None else "unknown"
    now = datetime.now(UTC)
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
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid_credentials",
        )

    token = create_access_token({"sub": payload.username})
    return {"access_token": token, "token_type": "bearer"}
