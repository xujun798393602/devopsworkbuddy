"""Create TP automation asset and result ingestion tables.

Revision ID: 0003_tp_automation
Revises: 0002_tp_plans_execution
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0003_tp_automation"
down_revision: str | None = "0002_tp_plans_execution"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create automation assets, suites, tasks and immutable ingestions."""
    op.create_table(
        "automation_assets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("normalized_name", sa.String(200), nullable=False),
        sa.Column("repository_ref", sa.Text(), nullable=False),
        sa.Column("case_version_ref", postgresql.UUID(as_uuid=True)),
        sa.UniqueConstraint("project_id", "normalized_name", name="uq_automation_asset_name"),
    )
    op.create_table(
        "automation_suites",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("normalized_name", sa.String(200), nullable=False),
        sa.Column("asset_ids", sa.JSON(), nullable=False),
        sa.UniqueConstraint("project_id", "normalized_name", name="uq_automation_suite_name"),
    )
    op.create_table(
        "automation_tasks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("suite_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("environment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("external_run_ref", sa.String(500), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
    )
    op.create_table(
        "result_ingestions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source", sa.String(100), nullable=False),
        sa.Column("external_run_ref", sa.String(500), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.UniqueConstraint("project_id", "source", "external_run_ref", name="uq_result_ingestion_run"),
    )
    op.create_table(
        "automation_result_items",
        sa.Column("ingestion_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("result_ingestions.id"), primary_key=True),
        sa.Column("sequence", sa.Integer(), primary_key=True),
        sa.Column("external_case_ref", sa.String(500), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("case_version_ref", postgresql.UUID(as_uuid=True)),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("message", sa.String(20000), nullable=False),
    )


def downgrade() -> None:
    """Drop automation tables in reverse order."""
    for table in ("automation_result_items", "result_ingestions", "automation_tasks", "automation_suites", "automation_assets"):
        op.drop_table(table)
