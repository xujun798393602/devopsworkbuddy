"""Append-only audit storage and role grants."""
import sqlalchemy as sa
from alembic import op

revision = "0001_audit_append_only"
down_revision = None


def upgrade() -> None:
    op.create_table(
        "audit_records",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("event_id", sa.String(128), nullable=False, unique=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("trace_id", sa.String(128), nullable=False),
        sa.Column("actor_id", sa.String(128), nullable=False),
        sa.Column("project_id", sa.String(36)),
        sa.Column("action", sa.String(128), nullable=False),
        sa.Column("result", sa.String(16), nullable=False),
        sa.Column("metadata_json", sa.JSON, nullable=False),
    )
    op.create_index(
        "ix_audit_time_id",
        "audit_records",
        [sa.text("occurred_at DESC"), sa.text("id DESC")],
    )


def downgrade() -> None:
    raise RuntimeError("Audit data downgrade is intentionally prohibited")
