from __future__ import annotations

from datetime import UTC, datetime
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from sqlalchemy import Text, cast, func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from adapters.storage.db import session_scope
from adapters.storage.models import CRMDLQModel, CRMOutboxModel
from core.domain.crm_outbox import OutboxItem
from core.ports.repositories import CRMOutboxRepository


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _to_domain(model: CRMOutboxModel) -> OutboxItem:
    return OutboxItem(
        id=model.id,
        aggregate_id=str(model.aggregate_id),
        operation=model.operation,
        payload=model.payload,
        status=model.status,
        attempts=model.attempts,
        next_retry_at=(
            _ensure_utc(model.next_retry_at) if model.next_retry_at is not None else None
        ),
        last_error=model.last_error,
        created_at=_ensure_utc(model.created_at),
        updated_at=_ensure_utc(model.updated_at),
    )


class PostgresCRMOutboxRepository(CRMOutboxRepository):
    async def enqueue_operation(
        self, aggregate_id: str, operation: str, payload: dict[str, object]
    ) -> UUID:
        item_id = uuid4()
        aggregate_uuid = self._parse_aggregate_id(aggregate_id)
        aggregate_value = str(aggregate_uuid)
        created_at = datetime.now(UTC)
        lock_key = f"{aggregate_value}:{operation}"
        pending_status = "pending"

        async with session_scope() as session:
            statement = (
                insert(CRMOutboxModel)
                .values(
                    id=item_id,
                    aggregate_id=aggregate_value,
                    operation=operation,
                    payload=payload,
                    status=pending_status,
                    attempts=0,
                    next_retry_at=None,
                    last_error=None,
                    created_at=created_at,
                    updated_at=created_at,
                )
                .on_conflict_do_nothing(
                    index_elements=[CRMOutboxModel.aggregate_id, CRMOutboxModel.operation],
                    # Keep this literal so Postgres can match the partial
                    # unique index predicate exactly.
                    index_where=text("status = 'pending'"),
                )
                .returning(CRMOutboxModel.id)
            )
            try:
                result = await session.execute(statement)
                created_id = result.scalar_one_or_none()
            except ProgrammingError as exc:
                if not self._is_missing_on_conflict_constraint(exc):
                    raise
                await self._acquire_outbox_lock(session, lock_key)
                created_id = await self._get_existing_pending_id(
                    session, aggregate_value, operation
                )
                if created_id is None:
                    fallback_statement = (
                        insert(CRMOutboxModel)
                        .values(
                            id=item_id,
                            aggregate_id=aggregate_value,
                            operation=operation,
                            payload=payload,
                            status=pending_status,
                            attempts=0,
                            next_retry_at=None,
                            last_error=None,
                            created_at=created_at,
                            updated_at=created_at,
                        )
                        .returning(CRMOutboxModel.id)
                    )
                    try:
                        fallback_result = await session.execute(fallback_statement)
                        created_id = fallback_result.scalar_one()
                    except IntegrityError:
                        created_id = await self._get_existing_pending_id(
                            session, aggregate_value, operation
                        )
                        if created_id is None:
                            raise

            if created_id is None:
                existing_id = await self._get_existing_pending_id(
                    session, aggregate_value, operation
                )
                if existing_id is None:
                    raise RuntimeError(
                        "crm_outbox_enqueue_failed: pending operation not created nor found"
                    )
                created_id = existing_id

        return created_id

    async def get_pending_batch(self, limit: int = 10) -> list[OutboxItem]:
        now = datetime.now(UTC)
        async with session_scope() as session:
            statement = (
                select(CRMOutboxModel)
                .where(
                    CRMOutboxModel.status == "pending",
                    (
                        CRMOutboxModel.next_retry_at.is_(None)
                        | (CRMOutboxModel.next_retry_at <= now)
                    ),
                )
                .order_by(CRMOutboxModel.created_at.asc())
                .with_for_update(skip_locked=True)
                .limit(limit)
            )
            result = await session.execute(statement)
            models = result.scalars().all()

            for model in models:
                model.status = "processing"
                model.updated_at = datetime.now(UTC)

        return [_to_domain(model) for model in models]

    async def mark_as_done(self, item_id: UUID) -> None:
        async with session_scope() as session:
            result = await session.execute(
                select(CRMOutboxModel).where(CRMOutboxModel.id == item_id)
            )
            model = result.scalar_one_or_none()
            if model is None:
                return

            model.status = "done"
            model.last_error = None
            model.next_retry_at = None
            model.updated_at = datetime.now(UTC)

    async def mark_as_failed_with_retry(
        self, item_id: UUID, error: str, next_retry_at: datetime, attempt: int
    ) -> None:
        async with session_scope() as session:
            result = await session.execute(
                select(CRMOutboxModel).where(CRMOutboxModel.id == item_id)
            )
            model = result.scalar_one_or_none()
            if model is None:
                return

            model.status = "pending"
            model.attempts = attempt
            model.last_error = error
            model.next_retry_at = next_retry_at
            model.updated_at = datetime.now(UTC)

    async def move_to_dlq(self, item_id: UUID, error: str) -> None:
        async with session_scope() as session:
            result = await session.execute(
                select(CRMOutboxModel).where(CRMOutboxModel.id == item_id)
            )
            model = result.scalar_one_or_none()
            if model is None:
                return

            session.add(
                CRMDLQModel(
                    id=uuid4(),
                    original_outbox_id=model.id,
                    payload=model.payload,
                    error=error,
                    moved_at=datetime.now(UTC),
                )
            )
            model.status = "dlq"
            model.last_error = error
            model.updated_at = datetime.now(UTC)

    async def count_dlq_items(self) -> int:
        async with session_scope() as session:
            statement = select(func.count()).select_from(CRMDLQModel)
            result = await session.execute(statement)
            return int(result.scalar_one())

    async def count_pending_items(self) -> int:
        async with session_scope() as session:
            statement = (
                select(func.count())
                .select_from(CRMOutboxModel)
                .where(CRMOutboxModel.status == "pending")
            )
            result = await session.execute(statement)
            return int(result.scalar_one())

    @staticmethod
    def _parse_aggregate_id(aggregate_id: str) -> UUID:
        try:
            return UUID(aggregate_id)
        except ValueError:
            return uuid5(NAMESPACE_URL, aggregate_id)

    @staticmethod
    def _is_missing_on_conflict_constraint(exc: ProgrammingError) -> bool:
        return "no unique or exclusion constraint matching the ON CONFLICT specification" in str(
            exc
        )

    @staticmethod
    async def _acquire_outbox_lock(session: AsyncSession, lock_key: str) -> None:
        await session.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))"),
            {"lock_key": lock_key},
        )

    @staticmethod
    async def _get_existing_pending_id(
        session: AsyncSession, aggregate_value: str, operation: str
    ) -> UUID | None:
        existing_result = await session.execute(
            select(CRMOutboxModel.id).where(
                cast(CRMOutboxModel.aggregate_id, Text) == aggregate_value,
                CRMOutboxModel.operation == operation,
                CRMOutboxModel.status == "pending",
            )
        )
        return existing_result.scalar_one_or_none()
