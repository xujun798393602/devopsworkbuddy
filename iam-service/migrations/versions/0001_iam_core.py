"""IAM private database baseline."""

import sqlalchemy as sa
from alembic import op

revision = "0001_iam_core"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create persistent users and refresh sessions."""
    op.create_table(
        "users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("username", sa.String(128), nullable=False, unique=True),
        sa.Column("display_name", sa.String(256), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("permissions", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
    )
    op.create_table(
        "sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("family_id", sa.String(36), nullable=False),
        sa.Column("current_refresh_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("previous_refresh_hash", sa.String(64), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("idle_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("auth_method", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("revoked_reason", sa.String(64), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
    )
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"])
    op.create_index("ix_sessions_family_id", "sessions", ["family_id"])
    op.create_index(
        "ix_sessions_previous_refresh_hash", "sessions", ["previous_refresh_hash"]
    )


def downgrade() -> None:
    """Drop the IAM baseline in dependency order."""
    op.drop_index("ix_sessions_previous_refresh_hash", table_name="sessions")
    op.drop_index("ix_sessions_family_id", table_name="sessions")
    op.drop_index("ix_sessions_user_id", table_name="sessions")
    op.drop_table("sessions")
    op.drop_table("users")
