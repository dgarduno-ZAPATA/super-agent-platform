from __future__ import annotations

from unittest.mock import Mock

from api.main import _check_admin_users


class _FakeResult:
    def __init__(self, value: int) -> None:
        self._value = value

    def scalar(self) -> int:
        return self._value


class _FakeSession:
    def __init__(self, active_count: int) -> None:
        self._active_count = active_count

    async def execute(self, _statement: object) -> _FakeResult:
        return _FakeResult(self._active_count)


async def test_startup_warns_when_no_active_users() -> None:
    logger = Mock()
    session = _FakeSession(active_count=0)

    count = await _check_admin_users(session=session, logger=logger)

    assert count == 0
    logger.warning.assert_called_once_with(
        "no_active_admin_users",
        hint="Run: docker compose exec app python scripts/migrate_admin_user.py",
    )
    logger.info.assert_not_called()


async def test_startup_ok_with_active_users() -> None:
    logger = Mock()
    session = _FakeSession(active_count=1)

    count = await _check_admin_users(session=session, logger=logger)

    assert count == 1
    logger.info.assert_called_once_with("admin_users_ok", active_count=1)
    logger.warning.assert_not_called()
