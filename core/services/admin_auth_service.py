from __future__ import annotations

import logging
import warnings
from typing import cast

from passlib.context import CryptContext  # type: ignore[import-untyped]

from core.ports.admin_user_repository import AdminUser, AdminUserRepository

# Suppress passlib+bcrypt version probe noise (bcrypt 4.x without __about__).
warnings.filterwarnings(
    "ignore",
    message=".*error reading bcrypt version.*",
    category=UserWarning,
)


# passlib emits this as a logger warning (not always via warnings module).
class _BcryptVersionNoiseFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return "error reading bcrypt version" not in record.getMessage().lower()


logging.getLogger("passlib.handlers.bcrypt").addFilter(_BcryptVersionNoiseFilter())

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class AdminAuthService:
    def __init__(self, repo: AdminUserRepository) -> None:
        self._repo = repo

    def hash_password(self, password: str) -> str:
        return cast(str, pwd_context.hash(password))

    def verify_password(self, plain: str, hashed: str) -> bool:
        return cast(bool, pwd_context.verify(plain, hashed))

    async def authenticate(self, username: str, password: str) -> AdminUser | None:
        user = await self._repo.get_by_username(username)
        if not user or not user.is_active:
            return None
        if not self.verify_password(password, user.password_hash):
            return None
        return user

    async def create_user(self, username: str, password: str) -> AdminUser:
        hashed = self.hash_password(password)
        return await self._repo.create(username, hashed)
