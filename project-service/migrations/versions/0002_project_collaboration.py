"""Add project collaboration, tasks, Worklogs, audit and Outbox."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # pgcrypto must exist before gen_random_uuid() is used in the owner backfill below.
    op.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto"')
    op.create_check_constraint("ck_projects_status", "projects", "status IN ('active','archived')")
    op.drop_constraint(
        "idempotency_records_resource_id_fkey", "idempotency_records", type_="foreignkey"
    )
    op.add_column(
        "idempotency_records",
        sa.Column(
            "operation", sa.String(500), nullable=False, server_default="POST /api/v1/projects"
        ),
    )
    op.add_column("idempotency_records", sa.Column("response_body", postgresql.JSONB()))
    op.add_column("idempotency_records", sa.Column("response_headers", postgresql.JSONB()))
    op.add_column("idempotency_records", sa.Column("expires_at", sa.DateTime(timezone=True)))
    # Drop the redundant state-machine constraint; ck_idempotency_status already covers the status check.
    op.drop_constraint("ck_idempotency_state", "idempotency_records", type_="check")
    op.create_index("ix_idempotency_expires", "idempotency_records", ["expires_at"])
    op.execute("CREATE SEQUENCE task_business_no_seq START WITH 1")
    op.create_table(
        "project_memberships",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("user_id", sa.String(255), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("joined_by", sa.String(255), nullable=False),
        sa.Column("removed_at", sa.DateTime(timezone=True)),
        sa.Column("removed_by", sa.String(255)),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "role IN ('owner','admin','member','viewer')", name="ck_membership_role"
        ),
        sa.CheckConstraint("status IN ('active','removed')", name="ck_membership_status"),
    )
    op.create_index(
        "uq_membership_active_user",
        "project_memberships",
        ["project_id", "user_id"],
        unique=True,
        postgresql_where=sa.text("status='active'"),
    )
    op.create_index(
        "uq_membership_active_owner",
        "project_memberships",
        ["project_id"],
        unique=True,
        postgresql_where=sa.text("status='active' AND role='owner'"),
    )
    op.create_index(
        "ix_membership_actor", "project_memberships", ["user_id", "status", "project_id"]
    )
    # Backfill owner memberships for existing projects; gen_random_uuid() requires pgcrypto.
    op.execute(
        "INSERT INTO project_memberships (id,project_id,user_id,role,status,joined_at,joined_by,version) "
        "SELECT gen_random_uuid(),id,owner_id,'owner','active',created_at,owner_id,1 FROM projects"
    )
    op.create_table(
        "project_counters",
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column("counter_type", sa.String(16), primary_key=True),
        sa.Column("next_value", sa.Integer(), nullable=False),
    )
    op.create_table(
        "release_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("business_no", sa.String(32), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("planned_release_date", sa.Date()),
        sa.Column("release_date", sa.Date()),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("project_id", "id", name="uq_versions_project_id"),
        sa.UniqueConstraint("project_id", "business_no", name="uq_versions_business_no"),
        sa.CheckConstraint(
            "status IN ('planned','active','released','canceled','archived')",
            name="ck_versions_status",
        ),
    )
    op.create_index(
        "uq_versions_normalized_name",
        "release_versions",
        ["project_id", sa.text("lower(btrim(name))")],
        unique=True,
    )
    op.create_index(
        "ix_versions_project_status", "release_versions", ["project_id", "status", "id"]
    )
    op.create_table(
        "iterations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("business_no", sa.String(32), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("goal", sa.Text(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("capacity_minutes", sa.Integer()),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("project_id", "id", name="uq_iterations_project_id"),
        sa.UniqueConstraint("project_id", "business_no", name="uq_iterations_business_no"),
        sa.CheckConstraint("end_date >= start_date", name="ck_iteration_dates"),
        sa.CheckConstraint(
            "capacity_minutes IS NULL OR capacity_minutes >= 0", name="ck_iteration_capacity"
        ),
        sa.CheckConstraint(
            "status IN ('planned','active','completed','canceled')", name="ck_iterations_status"
        ),
    )
    op.create_index(
        "uq_iterations_normalized_name",
        "iterations",
        ["project_id", sa.text("lower(btrim(name))")],
        unique=True,
    )
    op.create_index(
        "uq_iterations_active",
        "iterations",
        ["project_id"],
        unique=True,
        postgresql_where=sa.text("status='active'"),
    )
    op.create_index(
        "ix_iterations_project_status", "iterations", ["project_id", "status", "start_date", "id"]
    )
    op.create_table(
        "tasks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("business_no", sa.String(32), nullable=False, unique=True),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("task_type", sa.String(32), nullable=False),
        sa.Column("priority", sa.String(4), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("creator_id", sa.String(255), nullable=False),
        sa.Column("assignee_id", sa.String(255)),
        sa.Column("release_version_id", postgresql.UUID(as_uuid=True)),
        sa.Column("iteration_id", postgresql.UUID(as_uuid=True)),
        sa.Column("planned_start_at", sa.DateTime(timezone=True)),
        sa.Column("planned_end_at", sa.DateTime(timezone=True)),
        sa.Column("actual_start_at", sa.DateTime(timezone=True)),
        sa.Column("actual_end_at", sa.DateTime(timezone=True)),
        sa.Column("estimated_minutes", sa.Integer(), nullable=False),
        sa.Column("workflow_template_key", sa.String(64), nullable=False),
        sa.Column("workflow_version", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("project_id", "id", name="uq_tasks_project_id"),
        sa.ForeignKeyConstraint(
            ["project_id", "release_version_id"],
            ["release_versions.project_id", "release_versions.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "iteration_id"],
            ["iterations.project_id", "iterations.id"],
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "release_version_id IS NOT NULL OR iteration_id IS NOT NULL", name="ck_task_scope"
        ),
        sa.CheckConstraint("estimated_minutes BETWEEN 0 AND 10000000", name="ck_task_estimate"),
        sa.CheckConstraint(
            "planned_end_at IS NULL OR planned_start_at IS NULL OR planned_end_at >= planned_start_at",
            name="ck_task_planned_dates",
        ),
        sa.CheckConstraint(
            "status IN ('todo','in_progress','done','closed','canceled')", name="ck_task_status"
        ),
    )
    op.create_index(
        "ix_tasks_project_status", "tasks", ["project_id", "status", "created_at", "id"]
    )
    op.create_index(
        "ix_tasks_project_assignee", "tasks", ["project_id", "assignee_id", "status", "id"]
    )
    op.create_table(
        "task_participants",
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", sa.String(255), primary_key=True),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("added_by", sa.String(255), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id", "task_id"], ["tasks.project_id", "tasks.id"], ondelete="RESTRICT"
        ),
    )
    op.create_index(
        "ix_participants_project_user", "task_participants", ["project_id", "user_id", "task_id"]
    )
    op.create_table(
        "worklogs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.String(255), nullable=False),
        sa.Column("recorded_by", sa.String(255), nullable=False),
        sa.Column("work_date", sa.Date(), nullable=False),
        sa.Column("minutes_delta", sa.Integer(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column(
            "corrects_worklog_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("worklogs.id", ondelete="RESTRICT"),
        ),
        sa.Column("correction_reason", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id", "task_id"], ["tasks.project_id", "tasks.id"], ondelete="RESTRICT"
        ),
        sa.CheckConstraint(
            "minutes_delta != 0 AND minutes_delta BETWEEN -1440 AND 1440", name="ck_worklog_delta"
        ),
    )
    op.create_index(
        "ix_worklogs_task", "worklogs", ["project_id", "task_id", "work_date", "created_at", "id"]
    )
    op.create_index("ix_worklogs_user_day", "worklogs", ["project_id", "user_id", "work_date"])
    op.create_index("ix_worklogs_corrects", "worklogs", ["corrects_worklog_id"])
    op.create_table(
        "audit_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("trace_id", sa.String(255), nullable=False),
        sa.Column("actor_id", sa.String(255), nullable=False),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("resource_type", sa.String(64), nullable=False),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("result", sa.String(16), nullable=False),
        sa.Column("before", postgresql.JSONB(), nullable=False),
        sa.Column("after", postgresql.JSONB(), nullable=False),
        sa.Column("reason", sa.Text()),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("idempotency_key", sa.String(255)),
    )
    op.create_index("ix_audit_project_time", "audit_records", ["project_id", "occurred_at", "id"])
    op.create_index("ix_audit_trace", "audit_records", ["trace_id"])
    op.create_index(
        "ix_audit_resource", "audit_records", ["resource_type", "resource_id", "occurred_at"]
    )
    op.create_table(
        "outbox_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("event_type", sa.String(150), nullable=False),
        sa.Column("event_version", sa.Integer(), nullable=False),
        sa.Column("aggregate_type", sa.String(64), nullable=False),
        sa.Column("aggregate_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("trace_id", sa.String(255), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending','processing','published','failed')", name="ck_outbox_status"
        ),
    )
    op.create_index("ix_outbox_pending", "outbox_events", ["status", "available_at", "occurred_at"])


def downgrade() -> None:
    op.drop_index("ix_outbox_pending", table_name="outbox_events")
    op.drop_table("outbox_events")
    op.drop_index("ix_audit_resource", table_name="audit_records")
    op.drop_index("ix_audit_trace", table_name="audit_records")
    op.drop_index("ix_audit_project_time", table_name="audit_records")
    op.drop_table("audit_records")
    op.drop_index("ix_worklogs_corrects", table_name="worklogs")
    op.drop_index("ix_worklogs_user_day", table_name="worklogs")
    op.drop_index("ix_worklogs_task", table_name="worklogs")
    op.drop_table("worklogs")
    op.drop_index("ix_participants_project_user", table_name="task_participants")
    op.drop_table("task_participants")
    op.drop_index("ix_tasks_project_assignee", table_name="tasks")
    op.drop_index("ix_tasks_project_status", table_name="tasks")
    op.drop_table("tasks")
    op.drop_index("ix_iterations_project_status", table_name="iterations")
    op.drop_index("uq_iterations_active", table_name="iterations")
    op.drop_index("uq_iterations_normalized_name", table_name="iterations")
    op.drop_table("iterations")
    op.drop_index("ix_versions_project_status", table_name="release_versions")
    op.drop_index("uq_versions_normalized_name", table_name="release_versions")
    op.drop_table("release_versions")
    op.drop_table("project_counters")
    op.drop_index("ix_membership_actor", table_name="project_memberships")
    op.drop_index("uq_membership_active_owner", table_name="project_memberships")
    op.drop_index("uq_membership_active_user", table_name="project_memberships")
    op.drop_table("project_memberships")
    op.execute("DROP SEQUENCE IF EXISTS task_business_no_seq")
    op.drop_index("ix_idempotency_expires", table_name="idempotency_records")
    op.create_foreign_key(
        "idempotency_records_resource_id_fkey",
        "idempotency_records",
        "projects",
        ["resource_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_idempotency_state",
        "idempotency_records",
        "(status = 'processing' AND response_status IS NULL AND resource_id IS NULL AND completed_at IS NULL) "
        "OR (status = 'completed' AND response_status IS NOT NULL AND resource_id IS NOT NULL AND completed_at IS NOT NULL)",
    )
    op.drop_column("idempotency_records", "expires_at")
    op.drop_column("idempotency_records", "response_headers")
    op.drop_column("idempotency_records", "response_body")
    op.drop_column("idempotency_records", "operation")
    op.drop_constraint("ck_projects_status", "projects", type_="check")
