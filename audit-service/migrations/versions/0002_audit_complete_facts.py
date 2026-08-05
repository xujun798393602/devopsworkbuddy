"""Add complete immutable audit fact columns."""

import sqlalchemy as sa
from alembic import op

revision = "0002_audit_complete_facts"
down_revision = "0001_audit_append_only"


def upgrade() -> None:
    """Extend audit facts without introducing update or delete paths."""
    with op.batch_alter_table("audit_records") as batch:
        batch.add_column(sa.Column("actor_type", sa.String(32), nullable=False))
        batch.add_column(sa.Column("resource_type", sa.String(128), nullable=False))
        batch.add_column(sa.Column("resource_id", sa.String(128), nullable=False))
        batch.add_column(sa.Column("source", sa.String(128), nullable=False))
        batch.add_column(sa.Column("classification", sa.String(32), nullable=False))
    op.create_index(
        "ix_audit_project_time",
        "audit_records",
        ["project_id", "occurred_at"],
    )


def downgrade() -> None:
    """Prohibit destructive downgrade of immutable audit facts."""
    raise RuntimeError("Audit data downgrade is intentionally prohibited")
