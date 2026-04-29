from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.services.crm_worker import CRMSyncWorker


class _FakeScope:
    def set_extra(self, *_args, **_kwargs) -> None:
        return None


class _FakeSentry:
    @contextmanager
    def push_scope(self):
        yield _FakeScope()

    def capture_message(self, *_args, **_kwargs) -> None:
        return None


def _make_brand_config(dlq_threshold: int = 3, pending_threshold: int = 50) -> SimpleNamespace:
    return SimpleNamespace(
        brand=SimpleNamespace(
            alerts=SimpleNamespace(
                crm_dlq_threshold=dlq_threshold,
                crm_pending_threshold=pending_threshold,
            )
        )
    )


def _make_worker(
    dlq_count: int, pending_count: int, brand_config: SimpleNamespace
) -> CRMSyncWorker:
    outbox_repo = MagicMock()
    outbox_repo.count_dlq_items = AsyncMock(return_value=dlq_count)
    outbox_repo.count_pending_items = AsyncMock(return_value=pending_count)
    provider = MagicMock()
    return CRMSyncWorker(
        crm_outbox_repository=outbox_repo,
        crm_provider=provider,
        brand_config=brand_config,
    )


def _has_warning_event(warning_mock: MagicMock, event_name: str) -> bool:
    return any(call.args and call.args[0] == event_name for call in warning_mock.call_args_list)


@pytest.mark.asyncio
async def test_dlq_alert_fires_at_threshold() -> None:
    worker = _make_worker(
        dlq_count=5,
        pending_count=0,
        brand_config=_make_brand_config(dlq_threshold=3),
    )

    with (
        patch.dict("sys.modules", {"sentry_sdk": _FakeSentry()}),
        patch("core.services.crm_worker.logger.warning") as warning_mock,
    ):
        await worker._check_dlq_alerts()

    assert _has_warning_event(warning_mock, "crm_dlq_threshold_exceeded")


@pytest.mark.asyncio
async def test_dlq_alert_does_not_fire_below_threshold() -> None:
    worker = _make_worker(
        dlq_count=1,
        pending_count=0,
        brand_config=_make_brand_config(dlq_threshold=3),
    )

    with (
        patch.dict("sys.modules", {"sentry_sdk": _FakeSentry()}),
        patch("core.services.crm_worker.logger.warning") as warning_mock,
    ):
        await worker._check_dlq_alerts()

    assert not _has_warning_event(warning_mock, "crm_dlq_threshold_exceeded")


@pytest.mark.asyncio
async def test_pending_alert_fires_at_threshold() -> None:
    worker = _make_worker(
        dlq_count=0,
        pending_count=55,
        brand_config=_make_brand_config(pending_threshold=50),
    )

    with (
        patch.dict("sys.modules", {"sentry_sdk": _FakeSentry()}),
        patch("core.services.crm_worker.logger.warning") as warning_mock,
    ):
        await worker._check_dlq_alerts()

    assert _has_warning_event(warning_mock, "crm_pending_threshold_exceeded")


@pytest.mark.asyncio
async def test_dlq_check_failure_does_not_raise() -> None:
    outbox_repo = MagicMock()
    outbox_repo.count_dlq_items = AsyncMock(side_effect=Exception("db failed"))
    outbox_repo.count_pending_items = AsyncMock(return_value=0)
    worker = CRMSyncWorker(
        crm_outbox_repository=outbox_repo,
        crm_provider=MagicMock(),
        brand_config=_make_brand_config(),
    )

    with patch("core.services.crm_worker.logger.warning") as warning_mock:
        result = await worker._check_dlq_alerts()

    assert result is None
    assert _has_warning_event(warning_mock, "crm_dlq_check_failed")


@pytest.mark.asyncio
async def test_dlq_alert_at_exact_threshold() -> None:
    worker = _make_worker(
        dlq_count=3,
        pending_count=0,
        brand_config=_make_brand_config(dlq_threshold=3),
    )

    with (
        patch.dict("sys.modules", {"sentry_sdk": _FakeSentry()}),
        patch("core.services.crm_worker.logger.warning") as warning_mock,
    ):
        await worker._check_dlq_alerts()

    assert _has_warning_event(warning_mock, "crm_dlq_threshold_exceeded")


def test_alerts_config_defaults() -> None:
    from core.brand.schema import AlertsConfig

    cfg = AlertsConfig()
    assert cfg.crm_dlq_threshold >= 1
    assert cfg.crm_pending_threshold >= 1


def test_brand_config_has_alerts() -> None:
    from core.brand.schema import BrandConfig

    assert "alerts" in BrandConfig.model_fields
