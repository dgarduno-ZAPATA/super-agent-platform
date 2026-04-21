from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status
from jose import JWTError, ExpiredSignatureError, jwt

from core.config import get_settings


def create_access_token(data: dict[str, object], expires_minutes: int | None = None) -> str:
    settings = get_settings()
    expire_minutes = (
        settings.access_token_expire_minutes if expires_minutes is None else expires_minutes
    )
    to_encode = dict(data)
    expire_at = datetime.now(UTC) + timedelta(minutes=expire_minutes)
    to_encode["exp"] = int(expire_at.timestamp())
    return jwt.encode(to_encode, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def verify_token(token: str) -> dict[str, object]:
    if not token or not token.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid_or_missing_token",
        )

    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
    except ExpiredSignatureError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="token_expired",
        ) from exc
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid_token",
        ) from exc

    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid_token_payload",
        )
    return payload
