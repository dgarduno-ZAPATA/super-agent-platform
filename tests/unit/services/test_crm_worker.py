from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from core.domain.crm_outbox import OutboxItem
from core.domain.lead import Lead
from core.services.crm_worker import CRMSyncWorker


class FakeCRMOutboxRepository:
    def __init__(self, items: list[OutboxItem]) -> None:
        self.items = items
        self.done_ids: list[str] = []
        self.retry_calls: list[dict[str, object]] = []
        self.dlq_calls: list[dict[str, object]] = []

    async def enqueue_operation(
        self, aggregate_id: str, operation: str, payload: dict[str, object]
    ):
        del aggregate_id
        del operation
        del payload
        raise NotImplementedError

    async def get_pending_batch(self, limit: int = 10) -> list[OutboxItem]:
        return self.items[:limit]

    async def mark_as_done(self, item_id):
        self.done_ids.append(str(item_id))

    async def mark_as_failed_with_retry(self, item_id, error: str, next_retry_at, attempt: int):
        self.retry_calls.append(
            {
                "item_id": str(item_id),
                "error": error,
                "next_retry_at": next_retry_at,
                "attempt": attempt,
            }
        )

    async def move_to_dlq(self, item_id, error: str):
        self.dlq_calls.append({"item_id": str(item_id), "error": error})

    async def count_dlq_items(self) -> int:
        return 0

    async def count_pending_items(self) -> int:
        return 0


class FakeCRMProvider:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[dict[str, object]] = []

    async def upsert_lead(self, lead: Lead) -> str:
        self.calls.append({"operation": "upsert_lead", "lead": lead})
        if self.fail:
            raise RuntimeError("crm unavailable")
        return "crm-123"

    async def change_stage(self, lead_id: str, new_stage: str, reason: str | None = None) -> None:
        self.calls.append(
            {
                "operation": "change_stage",
                "lead_id": lead_id,
                "new_stage": new_stage,
                "reason": reason,
            }
        )
        if self.fail:
            raise RuntimeError("crm unavailable")

    async def add_note(self, lead_id: str, note: str, author: str) -> None:
        self.calls.append(
            {"operation": "add_note", "lead_id": lead_id, "note": note, "author": author}
        )
        if self.fail:
            raise RuntimeError("crm unavailable")

    async def assign_owner(self, lead_id: str, owner_id: str) -> None:
        del lead_id
        del owner_id
        raise NotImplementedError

    async def mark_do_not_contact(self, lead_id: str, reason: str) -> None:
        del lead_id
        del reason
        raise NotImplementedError

    async def schedule_reactivation(self, lead_id: str, not_before) -> None:
        del lead_id
        del not_before
        raise NotImplementedError


def _outbox_item(attempts: int = 0) -> OutboxItem:
    now = datetime.now(UTC)
    return OutboxItem(
        id=uuid4(),
        aggregate_id=str(uuid4()),
        operation="upsert_lead",
        payload={"phone": "5214421234567", "name": "Cliente"},
        status="pending",
        attempts=attempts,
        next_retry_at=None,
        last_error=None,
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_crm_worker_marks_done_on_success() -> None:
    item = _outbox_item(attempts=0)
    repo = FakeCRMOutboxRepository([item])
    provider = FakeCRMProvider(fail=False)
    worker = CRMSyncWorker(crm_outbox_repository=repo, crm_provider=provider)

    await worker.process_batch(batch_size=10)

    assert len(provider.calls) == 1
    assert repo.done_ids == [str(item.id)]
    assert repo.retry_calls == []
    assert repo.dlq_calls == []


@pytest.mark.asyncio
async def test_crm_worker_schedules_retry_on_failure_before_limit() -> None:
    item = _outbox_item(attempts=1)
    repo = FakeCRMOutboxRepository([item])
    provider = FakeCRMProvider(fail=True)
    worker = CRMSyncWorker(crm_outbox_repository=repo, crm_provider=provider)

    await worker.process_batch(batch_size=10)

    assert repo.done_ids == []
    assert len(repo.retry_calls) == 1
    assert repo.retry_calls[0]["attempt"] == 2
    assert repo.dlq_calls == []


@pytest.mark.asyncio
async def test_crm_worker_moves_to_dlq_after_three_attempts() -> None:
    item = _outbox_item(attempts=2)
    repo = FakeCRMOutboxRepository([item])
    provider = FakeCRMProvider(fail=True)
    worker = CRMSyncWorker(crm_outbox_repository=repo, crm_provider=provider)

    await worker.process_batch(batch_size=10)

    assert repo.done_ids == []
    assert repo.retry_calls == []
    assert len(repo.dlq_calls) == 1
    assert repo.dlq_calls[0]["item_id"] == str(item.id)
