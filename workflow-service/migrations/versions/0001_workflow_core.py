"""Workflow private schema."""
import sqlalchemy as sa
from alembic import op

revision = "0001_workflow_core"
down_revision = None


def upgrade() -> None:
    op.create_table(
        "workflow_template_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("template_key", sa.String(128), nullable=False),
        sa.Column("version_no", sa.Integer, nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("definition_json", sa.JSON, nullable=False),
        sa.UniqueConstraint("template_key", "version_no"),
    )
    op.create_table(
        "workflow_instances",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("current_state", sa.String(64), nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("workflow_instances")
    op.drop_table("workflow_template_versions")
