from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True, slots=True)
class AdminUser:
    id: uuid.UUID
    username: str
    password_hash: str
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None


class AdminUserRepository(Protocol):
    async def get_by_id(self, user_id: uuid.UUID) -> AdminUser | None: ...

    async def get_by_username(self, username: str) -> AdminUser | None: ...

    async def create(self, username: str, password_hash: str) -> AdminUser: ...

    async def update_last_login(self, user_id: uuid.UUID) -> None: ...

    async def list_all(self) -> list[AdminUser]: ...

    async def delete(self, user_id: uuid.UUID) -> None: ...

    async def set_active(self, user_id: uuid.UUID, is_active: bool) -> None: ...

    async def update_password(self, user_id: uuid.UUID, password_hash: str) -> None: ...
