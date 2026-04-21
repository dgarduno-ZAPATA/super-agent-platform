from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from jose import jwt

from core.auth.jwt_handler import create_access_token, verify_token
from core.config import get_settings


def test_create_and_verify_token_roundtrip() -> None:
    token = create_access_token({"sub": "admin"})

    payload = verify_token(token)

    assert payload["sub"] == "admin"
    assert "exp" in payload


def test_expired_token_raises_401() -> None:
    token = create_access_token({"sub": "admin"}, expires_minutes=-1)

    with pytest.raises(HTTPException) as exc_info:
        verify_token(token)

    assert exc_info.value.status_code == 401


def test_invalid_signature_raises_401() -> None:
    settings = get_settings()
    forged = jwt.encode(
        {"sub": "admin", "exp": int((datetime.now(UTC) + timedelta(minutes=10)).timestamp())},
        "not-the-right-secret",
        algorithm=settings.jwt_algorithm,
    )

    with pytest.raises(HTTPException) as exc_info:
        verify_token(forged)

    assert exc_info.value.status_code == 401


def test_missing_token_raises_401() -> None:
    with pytest.raises(HTTPException) as exc_info:
        verify_token("")

    assert exc_info.value.status_code == 401
