from __future__ import annotations

import os

import pytest

from core.config import get_settings


@pytest.fixture(scope="session", autouse=True)
def configure_test_runtime_flags() -> None:
    os.environ["CAMPAIGN_SCHEDULER_ENABLED"] = "false"
    get_settings.cache_clear()
