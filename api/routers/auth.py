from __future__ import annotations

import base64
import io
import re
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

import pyotp
import qrcode
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError

from adapters.storage.repositories.admin_totp_repo import PostgresAdminTOTPRepository
from api.dependencies import (
    get_admin_auth_service,
    get_admin_totp_repository,
    get_admin_user_repository,
    get_audit_log_service,
    get_brand,
    get_current_user,
    get_login_attempt_service,
)
from core.auth.jwt_handler import create_access_token, verify_token
from core.brand.schema import Brand
from core.ports.admin_user_repository import AdminUser, AdminUserRepository
from core.services.admin_auth_service import AdminAuthService
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


class AdminUserResponse(BaseModel):
    id: UUID
    username: str
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None


class CreateAdminUserRequest(BaseModel):
    username: str
    password: str


class AdminUserStatusRequest(BaseModel):
    is_active: bool


class UpdatePasswordRequest(BaseModel):
    new_password: str


_USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9.-]{3,50}$")


def _validate_username(username: str) -> str:
    candidate = username.strip()
    if not _USERNAME_PATTERN.fullmatch(candidate):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="username_debe_tener_3_50_y_solo_letras_numeros_puntos_guiones",
        )
    return candidate


def _validate_password(password: str) -> str:
    if len(password) < 8:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="password_minimo_8_caracteres",
        )
    return password


def _to_admin_user_response(record: AdminUser) -> AdminUserResponse:
    return AdminUserResponse(
        id=record.id,
        username=record.username,
        is_active=record.is_active,
        created_at=record.created_at,
        last_login_at=record.last_login_at,
    )


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
    admin_auth_service: Annotated[AdminAuthService, Depends(get_admin_auth_service)],
    admin_user_repository: Annotated[AdminUserRepository, Depends(get_admin_user_repository)],
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

    username = payload.username.strip()
    user = await admin_auth_service.authenticate(username, payload.password)
    if user is None:
        attempts.append(now)
        await login_attempt_service.record_attempt(
            ip=client_host,
            username=username,
            success=False,
        )
        await audit_log_service.log(
            actor="admin",
            action="login_failed",
            details={"username": username},
            ip_address=client_host,
            user_agent=user_agent,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid_credentials",
        )

    await login_attempt_service.record_attempt(
        ip=client_host,
        username=username,
        success=True,
    )
    totp_record = await admin_totp_repo.get(username)
    if totp_record is not None and totp_record.enabled:
        pre_auth_token = create_access_token(
            {"sub": username, "stage": "pre_auth"},
            expires_minutes=5,
        )
        return {
            "requires_2fa": True,
            "pre_auth_token": pre_auth_token,
        }

    token = create_access_token({"sub": username})
    await admin_user_repository.update_last_login(user.id)
    await audit_log_service.log(
        actor="admin",
        action="login_success",
        details={"username": username},
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


@router.get("/users", status_code=status.HTTP_200_OK)
async def list_admin_users(
    current_user: Annotated[dict[str, object], Depends(get_current_user)],
    admin_user_repository: Annotated[AdminUserRepository, Depends(get_admin_user_repository)],
) -> list[AdminUserResponse]:
    del current_user
    users = await admin_user_repository.list_all()
    return [_to_admin_user_response(user) for user in users]


@router.post("/users", status_code=status.HTTP_201_CREATED)
async def create_admin_user(
    payload: CreateAdminUserRequest,
    current_user: Annotated[dict[str, object], Depends(get_current_user)],
    admin_auth_service: Annotated[AdminAuthService, Depends(get_admin_auth_service)],
    admin_user_repository: Annotated[AdminUserRepository, Depends(get_admin_user_repository)],
) -> AdminUserResponse:
    del current_user
    username = _validate_username(payload.username)
    password = _validate_password(payload.password)

    existing = await admin_user_repository.get_by_username(username)
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="username_ya_existe")

    try:
        created = await admin_auth_service.create_user(username=username, password=password)
    except IntegrityError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="username_ya_existe",
        ) from exc
    return _to_admin_user_response(created)


@router.put("/users/{user_id}/status", status_code=status.HTTP_200_OK)
async def set_admin_user_status(
    user_id: UUID,
    payload: AdminUserStatusRequest,
    current_user: Annotated[dict[str, object], Depends(get_current_user)],
    admin_user_repository: Annotated[AdminUserRepository, Depends(get_admin_user_repository)],
) -> AdminUserResponse:
    requester_username = _assert_full_auth(current_user)
    target_user = await admin_user_repository.get_by_id(user_id)
    if target_user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="usuario_no_encontrado")
    if target_user.username == requester_username and not payload.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="no_puedes_desactivarte_a_ti_mismo",
        )
    await admin_user_repository.set_active(user_id, payload.is_active)
    refreshed = await admin_user_repository.get_by_id(user_id)
    if refreshed is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="usuario_no_encontrado")
    return _to_admin_user_response(refreshed)


@router.delete("/users/{user_id}", status_code=status.HTTP_200_OK)
async def deactivate_admin_user(
    user_id: UUID,
    current_user: Annotated[dict[str, object], Depends(get_current_user)],
    admin_user_repository: Annotated[AdminUserRepository, Depends(get_admin_user_repository)],
) -> AdminUserResponse:
    requester_username = _assert_full_auth(current_user)
    target_user = await admin_user_repository.get_by_id(user_id)
    if target_user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="usuario_no_encontrado")
    if target_user.username == requester_username:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="no_puedes_desactivarte_a_ti_mismo",
        )
    await admin_user_repository.set_active(user_id, False)
    refreshed = await admin_user_repository.get_by_id(user_id)
    if refreshed is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="usuario_no_encontrado")
    return _to_admin_user_response(refreshed)


@router.put("/users/{user_id}/password", status_code=status.HTTP_200_OK)
async def update_admin_user_password(
    user_id: UUID,
    payload: UpdatePasswordRequest,
    current_user: Annotated[dict[str, object], Depends(get_current_user)],
    admin_auth_service: Annotated[AdminAuthService, Depends(get_admin_auth_service)],
    admin_user_repository: Annotated[AdminUserRepository, Depends(get_admin_user_repository)],
) -> dict[str, str]:
    del current_user
    target_user = await admin_user_repository.get_by_id(user_id)
    if target_user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="usuario_no_encontrado")
    new_password = _validate_password(payload.new_password)
    new_hash = admin_auth_service.hash_password(new_password)
    await admin_user_repository.update_password(user_id=user_id, password_hash=new_hash)
    return {"message": "Contraseña actualizada"}
