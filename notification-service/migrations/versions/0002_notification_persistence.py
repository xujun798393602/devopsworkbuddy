"""Complete notification content, delivery, and preference persistence."""

import sqlalchemy as sa
from alembic import op

revision = "0002_notification_persistence"
down_revision = "0001_notifications"


def upgrade() -> None:
    """Add complete content, read state, versioning, and preferences."""
    with op.batch_alter_table("notifications") as batch:
        batch.add_column(sa.Column("category", sa.String(64), nullable=False))
        batch.add_column(sa.Column("target_url", sa.Text(), nullable=True))
        batch.add_column(sa.Column("severity", sa.String(16), nullable=False))
        batch.add_column(
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False)
        )
    with op.batch_alter_table("notification_deliveries") as batch:
        batch.add_column(
            sa.Column("read_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch.add_column(sa.Column("version", sa.Integer(), nullable=False))
    op.create_table(
        "notification_preferences",
        sa.Column("user_id", sa.String(128), nullable=False),
        sa.Column("category", sa.String(64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("locked", sa.Boolean(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("user_id", "category"),
    )
    op.create_index(
        "ix_notification_delivery_recipient_status",
        "notification_deliveries",
        ["recipient_id", "status"],
    )


def downgrade() -> None:
    """Remove production persistence extensions."""
    op.drop_index(
        "ix_notification_delivery_recipient_status",
        table_name="notification_deliveries",
    )
    op.drop_table("notification_preferences")
    with op.batch_alter_table("notification_deliveries") as batch:
        batch.drop_column("version")
        batch.drop_column("read_at")
    with op.batch_alter_table("notifications") as batch:
        batch.drop_column("created_at")
        batch.drop_column("severity")
        batch.drop_column("target_url")
        batch.drop_column("category")
