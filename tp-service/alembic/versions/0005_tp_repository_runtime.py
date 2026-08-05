"""Add durable legacy state, idempotency, and transactional Outbox tables."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_tp_repository_runtime"
down_revision: str | None = "0004_tp_trace_projection"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the frozen historical repository support schema."""
    op.create_table(
        "tp_unit_of_work_state",
        sa.Column("bucket", sa.String(length=64), nullable=False),
        sa.Column("key", sa.String(length=512), nullable=False),
        sa.Column("payload", sa.LargeBinary(), nullable=False),
        sa.PrimaryKeyConstraint("bucket", "key"),
    )
    op.create_table(
        "tp_outbox_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "tp_idempotency_records",
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("response_payload", sa.JSON(), nullable=False),
        sa.Column("response_status", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("project_id", "actor_id", "idempotency_key"),
    )


def downgrade() -> None:
    """Drop production repository support tables in dependency order."""
    op.drop_table("tp_idempotency_records")
    op.drop_table("tp_outbox_events")
    op.drop_table("tp_unit_of_work_state")
