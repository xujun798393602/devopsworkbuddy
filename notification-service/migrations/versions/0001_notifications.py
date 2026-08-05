"""Notification fact/delivery private schema."""
import sqlalchemy as sa
from alembic import op

revision = "0001_notifications"
down_revision = None


def upgrade() -> None:
    op.create_table(
        "notifications",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("source_event_id", sa.String(128), nullable=False),
        sa.Column("template_key", sa.String(128), nullable=False),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("body", sa.Text, nullable=False),
    )
    op.create_table(
        "notification_deliveries",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("notification_id", sa.String(36), nullable=False),
        sa.Column("recipient_id", sa.String(128), nullable=False),
        sa.Column("source_event_id", sa.String(128), nullable=False),
        sa.Column("template_key", sa.String(128), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.UniqueConstraint("recipient_id", "source_event_id", "template_key"),
    )


def downgrade() -> None:
    op.drop_table("notification_deliveries")
    op.drop_table("notifications")
