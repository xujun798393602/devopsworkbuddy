"""Create source-owned trace link projection tables.

Revision ID: 0004_tp_trace_projection
Revises: 0003_tp_automation
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0004_tp_trace_projection"
down_revision: str | None = "0003_tp_automation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create immutable links and idempotent consumer checkpoints."""
    op.create_table(
        "traceability_links",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_domain", sa.String(32), nullable=False),
        sa.Column("source_type", sa.String(64), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_revision", sa.Integer(), nullable=False),
        sa.Column("target_domain", sa.String(32), nullable=False),
        sa.Column("target_type", sa.String(64), nullable=False),
        sa.Column("target_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_revision", sa.Integer(), nullable=False),
        sa.Column("link_type", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("source_event_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('active','superseded','broken')", name="ck_trace_link_status"),
    )
    op.create_index("ix_trace_forward", "traceability_links", ["project_id", "source_id", "status"])
    op.create_index("ix_trace_reverse", "traceability_links", ["project_id", "target_id", "status"])
    op.create_table(
        "trace_projection_checkpoints",
        sa.Column("consumer", sa.String(100), primary_key=True),
        sa.Column("last_event_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_event_id", postgresql.UUID(as_uuid=True), nullable=False),
    )


def downgrade() -> None:
    """Drop projection state and links."""
    op.drop_table("trace_projection_checkpoints")
    op.drop_index("ix_trace_reverse", table_name="traceability_links")
    op.drop_index("ix_trace_forward", table_name="traceability_links")
    op.drop_table("traceability_links")
