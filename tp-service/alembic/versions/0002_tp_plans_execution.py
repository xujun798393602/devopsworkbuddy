"""Create TP planning and execution tables.

Revision ID: 0002_tp_plans_execution
Revises: 0001_tp_library_design
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0002_tp_plans_execution"
down_revision: str | None = "0001_tp_library_design"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create environments, frozen scopes, executions, attempts and reports."""
    op.create_table(
        "test_environments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("normalized_name", sa.String(200), nullable=False),
        sa.Column("classification", sa.String(16), nullable=False),
        sa.Column("base_url", sa.Text(), nullable=False),
        sa.Column("configuration_summary", sa.String(8192), nullable=False),
        sa.Column("variable_keys", sa.JSON(), nullable=False),
        sa.Column("secret_ref_count", sa.Integer(), nullable=False),
        sa.UniqueConstraint("project_id", "normalized_name", name="uq_environment_name"),
    )
    op.create_table(
        "test_plans",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_no", sa.String(64), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("scope_hash", sa.String(64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.UniqueConstraint("project_id", "business_no", name="uq_plan_business_no"),
    )
    op.create_table(
        "plan_scope_items",
        sa.Column("plan_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("test_plans.id"), primary_key=True),
        sa.Column("sequence", sa.Integer(), primary_key=True),
        sa.Column("requirement_ref", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("requirement_revision", sa.Integer(), nullable=False),
        sa.Column("requirement_hash", sa.String(64), nullable=False),
        sa.Column("case_version_ref", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("environment_id", postgresql.UUID(as_uuid=True), nullable=False),
    )
    op.create_table(
        "test_executions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("plan_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("test_plans.id"), nullable=False),
        sa.Column("environment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("assignee_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("round_no", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.UniqueConstraint("plan_id", "round_no", name="uq_execution_round"),
    )
    op.create_table(
        "case_run_attempts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("execution_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("test_executions.id"), nullable=False),
        sa.Column("case_version_ref", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("actual_result", sa.Text(), nullable=False),
        sa.UniqueConstraint("execution_id", "case_version_ref", "attempt_no", name="uq_case_run_attempt"),
    )
    op.create_table(
        "test_reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("execution_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("test_executions.id"), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("published_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("summary", sa.JSON(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.UniqueConstraint("execution_id", "revision", name="uq_report_revision"),
    )


def downgrade() -> None:
    """Drop planning and execution tables in reverse order."""
    for table in ("test_reports", "case_run_attempts", "test_executions", "plan_scope_items", "test_plans", "test_environments"):
        op.drop_table(table)
