"""Create the frozen requirement aggregate and revision baseline schema."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_requirement_baseline"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create only the tables owned by this immutable baseline revision."""
    op.create_table(
        "requirements",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), nullable=False),
        sa.Column("business_no", sa.String(64), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("type", sa.String(32), nullable=False),
        sa.Column("owner_id", sa.String(36), nullable=False),
        sa.Column("release_version_id", sa.String(36), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("parent_id", sa.String(36), nullable=True),
        sa.Column("priority", sa.String(8), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("acceptance_criteria", sa.JSON(), nullable=False),
        sa.Column("current_revision", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("baseline_status", sa.String(32), nullable=False),
        sa.UniqueConstraint(
            "project_id", "business_no", name="uq_requirement_project_business_no"
        ),
    )
    op.create_index("ix_requirements_project_id", "requirements", ["project_id"])
    op.create_table(
        "requirement_revisions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("requirement_id", sa.String(36), nullable=False),
        sa.Column("revision_no", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.UniqueConstraint(
            "requirement_id", "revision_no", name="uq_requirement_revision_no"
        ),
    )
    op.create_index(
        "ix_requirement_revisions_requirement_id",
        "requirement_revisions",
        ["requirement_id"],
    )


def downgrade() -> None:
    """Drop the frozen baseline in reverse dependency order."""
    op.drop_index(
        "ix_requirement_revisions_requirement_id",
        table_name="requirement_revisions",
    )
    op.drop_table("requirement_revisions")
    op.drop_index("ix_requirements_project_id", table_name="requirements")
    op.drop_table("requirements")
