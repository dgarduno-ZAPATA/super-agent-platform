"""add login attempts table

Revision ID: 20260422_0004
Revises: 20260422_0003
Create Date: 2026-04-22 00:10:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20260422_0004"
down_revision: str | None = "20260422_0003"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "login_attempts",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("ip_address", sa.Text(), nullable=False),
        sa.Column("username", sa.Text(), nullable=True),
        sa.Column(
            "attempted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("success", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.execute(
        "CREATE INDEX idx_login_attempts_ip_time "
        "ON login_attempts(ip_address, attempted_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_login_attempts_ip_time")
    op.drop_table("login_attempts")
