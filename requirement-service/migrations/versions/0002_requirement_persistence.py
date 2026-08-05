"""Add governance, project-scoped idempotency, and transactional outbox."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_requirement_persistence"
down_revision: str | None = "0001_requirement_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create normalized governance and command infrastructure tables."""
    op.create_table(
        "requirement_review_rounds",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("requirement_id", sa.String(36), nullable=False),
        sa.Column("round_no", sa.Integer(), nullable=False),
        sa.Column("revision_id", sa.String(36), nullable=False),
        sa.Column("submitted_by", sa.String(36), nullable=False),
        sa.Column("reviewer_ids", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("decisions", sa.JSON(), nullable=False),
        sa.UniqueConstraint(
            "requirement_id", "round_no", name="uq_requirement_review_round_no"
        ),
    )
    op.create_index(
        "ix_requirement_review_rounds_requirement_id",
        "requirement_review_rounds",
        ["requirement_id"],
    )
    op.create_table(
        "requirement_baselines",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("baseline_no", sa.String(64), nullable=False),
        sa.Column("release_version_id", sa.String(36), nullable=False),
        sa.Column("revision_refs", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.UniqueConstraint(
            "project_id", "baseline_no", name="uq_requirement_baseline_no"
        ),
    )
    op.create_index(
        "ix_requirement_baselines_project_id",
        "requirement_baselines",
        ["project_id"],
    )
    op.create_table(
        "requirement_change_requests",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("requirement_id", sa.String(36), nullable=False),
        sa.Column("base_revision_id", sa.String(36), nullable=False),
        sa.Column("proposed_patch", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
    )
    op.create_index(
        "ix_requirement_change_requests_project_id",
        "requirement_change_requests",
        ["project_id"],
    )
    op.create_index(
        "ix_requirement_change_requests_requirement_id",
        "requirement_change_requests",
        ["requirement_id"],
    )
    op.create_table(
        "idempotency_records",
        sa.Column("project_id", sa.String(36), primary_key=True),
        sa.Column("actor_id", sa.String(36), primary_key=True),
        sa.Column("idempotency_key", sa.String(128), primary_key=True),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("response_body", sa.JSON(), nullable=False),
        sa.Column("response_status", sa.Integer(), nullable=False),
    )
    op.create_table(
        "outbox_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
    )


def downgrade() -> None:
    """Drop production tables in reverse dependency order."""
    op.drop_table("outbox_events")
    op.drop_table("idempotency_records")
    op.drop_index(
        "ix_requirement_change_requests_requirement_id",
        table_name="requirement_change_requests",
    )
    op.drop_index(
        "ix_requirement_change_requests_project_id",
        table_name="requirement_change_requests",
    )
    op.drop_table("requirement_change_requests")
    op.drop_index(
        "ix_requirement_baselines_project_id",
        table_name="requirement_baselines",
    )
    op.drop_table("requirement_baselines")
    op.drop_index(
        "ix_requirement_review_rounds_requirement_id",
        table_name="requirement_review_rounds",
    )
    op.drop_table("requirement_review_rounds")
