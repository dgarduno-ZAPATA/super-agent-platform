from __future__ import annotations

from datetime import UTC, datetime, timedelta
import math

from adapters.storage.repositories.login_attempt_repo import PostgresLoginAttemptRepository

MAX_FAILURES = 5
LOCKOUT_MINUTES = 15


class LoginAttemptService:
    def __init__(self, repo: PostgresLoginAttemptRepository) -> None:
        self.repo = repo

    async def check_lockout(self, ip: str) -> bool:
        cutoff = datetime.now(UTC) - timedelta(minutes=LOCKOUT_MINUTES)
        failures = await self.repo.count_failures_since(ip=ip, since=cutoff)
        return failures >= MAX_FAILURES

    async def record_attempt(self, ip: str, username: str | None, success: bool) -> None:
        await self.repo.insert(ip=ip, username=username, success=success)

    async def get_remaining_lockout(self, ip: str) -> int:
        cutoff = datetime.now(UTC) - timedelta(minutes=LOCKOUT_MINUTES)
        oldest_failure = await self.repo.oldest_failure_since(ip=ip, since=cutoff)
        if oldest_failure is None:
            return 0

        lockout_ends_at = oldest_failure + timedelta(minutes=LOCKOUT_MINUTES)
        remaining_seconds = (lockout_ends_at - datetime.now(UTC)).total_seconds()
        if remaining_seconds <= 0:
            return 0
        return max(1, int(math.ceil(remaining_seconds / 60)))
