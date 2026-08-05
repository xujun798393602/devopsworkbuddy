"""Create TP library and design tables.

Revision ID: 0001_tp_library_design
Revises:
"""
from collections.abc import Sequence

from sqlalchemy import text

from alembic import op

revision: str = "0001_tp_library_design"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the exact SQLAlchemy metadata for batch P0-A."""
    from tp_service.persistence import Base

    bind = op.get_bind()
    baseline_tables = (
        "test_folders",
        "test_cases",
        "test_case_versions",
        "test_case_steps",
        "design_sessions",
        "stage_runs",
        "review_gates",
        "import_batches",
    )
    Base.metadata.create_all(
        bind=bind,
        tables=[Base.metadata.tables[name] for name in baseline_tables],
    )
    op.execute(text("CREATE INDEX IF NOT EXISTS ix_folder_project_parent ON test_folders(project_id, parent_id)"))


def downgrade() -> None:
    """Drop batch P0-A in reverse dependency order."""
    from tp_service.persistence import Base

    baseline_tables = (
        "import_batches",
        "review_gates",
        "stage_runs",
        "design_sessions",
        "test_case_steps",
        "test_case_versions",
        "test_cases",
        "test_folders",
    )
    Base.metadata.drop_all(
        bind=op.get_bind(),
        tables=[Base.metadata.tables[name] for name in baseline_tables],
    )
