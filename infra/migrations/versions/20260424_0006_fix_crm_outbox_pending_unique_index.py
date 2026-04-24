"""ensure partial unique index for pending crm outbox operations

Revision ID: 20260424_0006
Revises: 20260422_0005
Create Date: 2026-04-24 18:35:00.000000
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260424_0006"
down_revision: str | None = "20260422_0005"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    # Keep one pending row per (aggregate_id, operation) so the unique index can be created safely.
    op.execute(
        """
        WITH ranked_pending AS (
            SELECT
                id,
                ROW_NUMBER() OVER (
                    PARTITION BY aggregate_id, operation
                    ORDER BY created_at ASC, id ASC
                ) AS row_num
            FROM crm_outbox
            WHERE status = 'pending'
        )
        DELETE FROM crm_outbox AS target
        USING ranked_pending AS ranked
        WHERE target.id = ranked.id
          AND ranked.row_num > 1
        """
    )

    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_crm_outbox_pending_operation
        ON crm_outbox (aggregate_id, operation)
        WHERE status = 'pending'
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_crm_outbox_pending_operation")
