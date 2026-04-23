from __future__ import annotations

import base64
import io
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta
from typing import Annotated

import pyotp
import qrcode
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from adapters.storage.repositories.admin_totp_repo import PostgresAdminTOTPRepository
from api.dependencies import (
    get_admin_totp_repository,
    get_audit_log_service,
    get_brand,
    get_current_user,
    get_login_attempt_service,
)
from core.auth.jwt_handler import create_access_token, verify_token
from core.brand.schema import Brand
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


class TwoFactorConfirmRequest(BaseModel):
    code: str


class TwoFactorLoginRequest(BaseModel):
    pre_auth_token: str
    code: str


def _assert_full_auth(current_user: dict[str, object]) -> str:
    stage = str(current_user.get("stage") or "")
    if stage == "pre_auth":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_token")
    return str(current_user.get("sub") or "admin")


@router.post("/token", status_code=status.HTTP_200_OK)
async def issue_token(
    payload: TokenRequest,
    request: Request,
    audit_log_service: Annotated[AuditLogService, Depends(get_audit_log_service)],
    login_attempt_service: Annotated[LoginAttemptService, Depends(get_login_attempt_service)],
    admin_totp_repo: Annotated[PostgresAdminTOTPRepository, Depends(get_admin_totp_repository)],
) -> dict[str, object]:
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
    totp_record = await admin_totp_repo.get(payload.username)
    if totp_record is not None and totp_record.enabled:
        pre_auth_token = create_access_token(
            {"sub": payload.username, "stage": "pre_auth"},
            expires_minutes=5,
        )
        return {
            "requires_2fa": True,
            "pre_auth_token": pre_auth_token,
        }

    token = create_access_token({"sub": payload.username})
    await audit_log_service.log(
        actor="admin",
        action="login_success",
        details={"username": payload.username},
        ip_address=client_host,
        user_agent=user_agent,
    )
    return {"access_token": token, "token_type": "bearer", "requires_2fa": False}


@router.post("/2fa/setup", status_code=status.HTTP_200_OK)
async def setup_2fa(
    current_user: Annotated[dict[str, object], Depends(get_current_user)],
    brand: Annotated[Brand, Depends(get_brand)],
    admin_totp_repo: Annotated[PostgresAdminTOTPRepository, Depends(get_admin_totp_repository)],
) -> dict[str, str]:
    username = _assert_full_auth(current_user)
    secret = pyotp.random_base32()
    totp = pyotp.TOTP(secret)
    uri = totp.provisioning_uri(name=username, issuer_name=brand.brand.name)

    qr_img = qrcode.make(uri)
    buffer = io.BytesIO()
    qr_img.save(buffer, format="PNG")
    qr_b64 = base64.b64encode(buffer.getvalue()).decode("utf-8")

    await admin_totp_repo.upsert(username=username, secret=secret, enabled=False)
    return {"qr_code": f"data:image/png;base64,{qr_b64}", "secret": secret}


@router.post("/2fa/confirm", status_code=status.HTTP_200_OK)
async def confirm_2fa(
    payload: TwoFactorConfirmRequest,
    current_user: Annotated[dict[str, object], Depends(get_current_user)],
    admin_totp_repo: Annotated[PostgresAdminTOTPRepository, Depends(get_admin_totp_repository)],
) -> dict[str, str]:
    username = _assert_full_auth(current_user)
    record = await admin_totp_repo.get(username=username)
    if record is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Ejecuta setup primero")

    totp = pyotp.TOTP(record.totp_secret)
    if not totp.verify(payload.code, valid_window=1):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Código inválido")

    await admin_totp_repo.enable(username=username)
    return {"status": "2fa_enabled"}


@router.get("/2fa/status", status_code=status.HTTP_200_OK)
async def get_2fa_status(
    current_user: Annotated[dict[str, object], Depends(get_current_user)],
    admin_totp_repo: Annotated[PostgresAdminTOTPRepository, Depends(get_admin_totp_repository)],
) -> dict[str, bool]:
    username = _assert_full_auth(current_user)
    record = await admin_totp_repo.get(username=username)
    return {"enabled": bool(record.enabled) if record is not None else False}


@router.post("/2fa/login", status_code=status.HTTP_200_OK)
async def complete_2fa_login(
    payload: TwoFactorLoginRequest,
    admin_totp_repo: Annotated[PostgresAdminTOTPRepository, Depends(get_admin_totp_repository)],
) -> dict[str, str]:
    token_payload = verify_token(payload.pre_auth_token)
    if str(token_payload.get("stage") or "") != "pre_auth":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido")

    username = str(token_payload.get("sub") or "")
    if not username:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido")

    record = await admin_totp_repo.get(username=username)
    if record is None or not record.enabled:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="2FA no configurado")

    totp = pyotp.TOTP(record.totp_secret)
    if not totp.verify(payload.code, valid_window=1):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Código inválido")

    full_token = create_access_token({"sub": username})
    return {"access_token": full_token, "token_type": "bearer"}
