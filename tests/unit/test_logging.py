from __future__ import annotations

import io
import json
from unittest.mock import patch

import structlog

from core.observability.context import bind_context, clear_context
from core.observability.logging import mask_pii, setup_logging


def test_mask_pii_masks_mexican_phone() -> None:
    assert mask_pii("+52 5512341234", "phone") == "+52***1234"


def test_mask_pii_masks_email() -> None:
    assert mask_pii("estefania@selectruckszapata.com", "email") == "e***@s***"


def test_mask_pii_masks_name() -> None:
    assert mask_pii("Estefania Zapata", "name") == "E*** Z***"


def test_bind_context_is_included_in_structlog_output() -> None:
    stream = io.StringIO()
    with patch("sys.stdout", stream):
        setup_logging("INFO")
        clear_context()
        bind_context(
            request_id="req-123",
            conversation_id="conv-456",
            lead_id="lead-789",
            campaign_id="campaign-001",
            tenant_id="tenant-xyz",
        )

        logger = structlog.get_logger("test_logger")
        logger.info(
            "log_emitted",
            phone="+52 5512341234",
            email="lead@example.com",
            name="Juan Perez",
        )

    log_entry = json.loads(stream.getvalue().strip())

    assert log_entry["event"] == "log_emitted"
    assert log_entry["request_id"] == "req-123"
    assert log_entry["conversation_id"] == "conv-456"
    assert log_entry["lead_id"] == "lead-789"
    assert log_entry["campaign_id"] == "campaign-001"
    assert log_entry["tenant_id"] == "tenant-xyz"
    assert log_entry["phone"] == "+52***1234"
    assert log_entry["email"] == "l***@e***"
    assert log_entry["name"] == "J*** P***"
