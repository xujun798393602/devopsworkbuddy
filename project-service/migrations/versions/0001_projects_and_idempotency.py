"""Create projects and idempotency persistence."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SEQUENCE project_business_no_seq START WITH 1")
    op.create_table(
        "projects",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("business_no", sa.String(32), nullable=False, unique=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("owner_id", sa.String(255), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_projects_owner_id", "projects", ["owner_id"])
    op.create_table(
        "idempotency_records",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("scope", sa.String(300), nullable=False),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("response_status", sa.Integer()),
        sa.Column(
            "resource_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="RESTRICT"),
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("scope", "idempotency_key", name="uq_idempotency_scope_key"),
        sa.CheckConstraint("status IN ('processing', 'completed')", name="ck_idempotency_status"),
        sa.CheckConstraint(
            "(status = 'processing' AND response_status IS NULL AND resource_id IS NULL AND completed_at IS NULL) OR (status = 'completed' AND response_status IS NOT NULL AND resource_id IS NOT NULL AND completed_at IS NOT NULL)",
            name="ck_idempotency_state",
        ),
    )


def downgrade() -> None:
    op.drop_table("idempotency_records")
    op.drop_index("ix_projects_owner_id", table_name="projects")
    op.drop_table("projects")
    op.execute("DROP SEQUENCE project_business_no_seq")
