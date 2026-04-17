from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import text

from adapters.storage.db import session_scope
from adapters.storage.repositories.crm_outbox_repo import PostgresCRMOutboxRepository
from tests.integration.storage.conftest import run_async


def _cleanup_tables() -> None:
    async def _delete_rows() -> None:
        async with session_scope() as session:
            await session.execute(text("DELETE FROM crm_dlq"))
            await session.execute(text("DELETE FROM crm_outbox"))

    run_async(_delete_rows())


def test_crm_outbox_enqueue_get_batch_and_move_to_dlq(clean_event_tables: None) -> None:
    _cleanup_tables()
    repo = PostgresCRMOutboxRepository()
    aggregate_id = str(uuid4())

    item_id = run_async(
        repo.enqueue_operation(
            aggregate_id=aggregate_id,
            operation="upsert_lead",
            payload={"phone": "5214421234567", "name": "Cliente"},
        )
    )
    batch = run_async(repo.get_pending_batch(limit=10))

    assert len(batch) == 1
    assert str(batch[0].id) == str(item_id)
    assert batch[0].operation == "upsert_lead"

    run_async(repo.move_to_dlq(batch[0].id, "permanent failure"))

    async def _counts() -> tuple[int, int]:
        async with session_scope() as session:
            outbox_result = await session.execute(
                text("SELECT COUNT(*) FROM crm_outbox WHERE status = 'dlq'")
            )
            dlq_result = await session.execute(text("SELECT COUNT(*) FROM crm_dlq"))
            return int(outbox_result.scalar_one()), int(dlq_result.scalar_one())

    outbox_dlq_count, dlq_count = run_async(_counts())
    assert outbox_dlq_count == 1
    assert dlq_count == 1


def test_crm_outbox_get_pending_batch_respects_retry_window(clean_event_tables: None) -> None:
    _cleanup_tables()
    repo = PostgresCRMOutboxRepository()
    aggregate_id_due = str(uuid4())
    aggregate_id_later = str(uuid4())

    due_item_id = run_async(
        repo.enqueue_operation(
            aggregate_id=aggregate_id_due,
            operation="upsert_lead",
            payload={"phone": "5214421000001"},
        )
    )
    later_item_id = run_async(
        repo.enqueue_operation(
            aggregate_id=aggregate_id_later,
            operation="upsert_lead",
            payload={"phone": "5214421000002"},
        )
    )

    run_async(
        repo.mark_as_failed_with_retry(
            item_id=later_item_id,
            error="temporary",
            next_retry_at=datetime.now(UTC) + timedelta(minutes=20),
            attempt=1,
        )
    )

    batch = run_async(repo.get_pending_batch(limit=10))

    assert len(batch) == 1
    assert str(batch[0].id) == str(due_item_id)
