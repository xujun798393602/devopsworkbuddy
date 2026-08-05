"""Complete workflow aggregate, idempotency, history, and outbox schema."""
import sqlalchemy as sa
from alembic import op

revision = "0002_workflow_persistence"
down_revision = "0001_workflow_core"


def upgrade() -> None:
    """Upgrade the private workflow database to the production schema."""
    op.add_column(
        "workflow_template_versions",
        sa.Column("name", sa.String(200), nullable=True),
    )
    op.execute(
        "UPDATE workflow_template_versions "
        "SET name = template_key WHERE name IS NULL"
    )
    op.alter_column("workflow_template_versions", "name", nullable=False)

    op.add_column(
        "workflow_instances",
        sa.Column("business_object_type", sa.String(64), nullable=True),
    )
    op.add_column(
        "workflow_instances",
        sa.Column("business_object_id", sa.String(128), nullable=True),
    )
    op.add_column(
        "workflow_instances",
        sa.Column("template_key", sa.String(128), nullable=True),
    )
    op.add_column(
        "workflow_instances",
        sa.Column("template_version", sa.Integer(), nullable=True),
    )
    op.add_column(
        "workflow_instances",
        sa.Column("started_by", sa.String(128), nullable=True),
    )
    op.add_column(
        "workflow_instances",
        sa.Column("status", sa.String(16), nullable=True),
    )
    op.execute(
        "UPDATE workflow_instances SET "
        "business_object_type = 'unknown', "
        "business_object_id = id, "
        "template_key = 'system.task-lifecycle', "
        "template_version = 1, "
        "started_by = 'migration', "
        "status = 'active'"
    )
    for column in (
        "business_object_type",
        "business_object_id",
        "template_key",
        "template_version",
        "started_by",
        "status",
    ):
        op.alter_column("workflow_instances", column, nullable=False)
    op.create_index(
        "ix_workflow_instances_project_id",
        "workflow_instances",
        ["project_id"],
    )

    op.create_table(
        "workflow_transitions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("instance_id", sa.String(36), nullable=False),
        sa.Column("from_state", sa.String(64), nullable=False),
        sa.Column("to_state", sa.String(64), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("actor_id", sa.String(128), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_workflow_transitions_instance_id",
        "workflow_transitions",
        ["instance_id"],
    )
    op.create_table(
        "workflow_commands",
        sa.Column("actor_id", sa.String(128), primary_key=True),
        sa.Column("idempotency_key", sa.String(128), primary_key=True),
        sa.Column("signature", sa.String(64), nullable=False),
        sa.Column("result_instance_id", sa.String(36), nullable=False),
    )
    op.create_table(
        "workflow_outbox",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("event_type", sa.String(128), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column(
            "status",
            sa.String(16),
            nullable=False,
            server_default="pending",
        ),
    )


def downgrade() -> None:
    """Remove production persistence additions."""
    op.drop_table("workflow_outbox")
    op.drop_table("workflow_commands")
    op.drop_index(
        "ix_workflow_transitions_instance_id",
        table_name="workflow_transitions",
    )
    op.drop_table("workflow_transitions")
    op.drop_index(
        "ix_workflow_instances_project_id",
        table_name="workflow_instances",
    )
    for column in (
        "status",
        "started_by",
        "template_version",
        "template_key",
        "business_object_id",
        "business_object_type",
    ):
        op.drop_column("workflow_instances", column)
    op.drop_column("workflow_template_versions", "name")
