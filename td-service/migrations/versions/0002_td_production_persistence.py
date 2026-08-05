"""Add durable evidence, idempotency and SLA observations.

Revision ID: 0002_td_production_persistence
Revises: 0001_td_baseline
"""
from collections.abc import Sequence

from alembic import op
from sqlalchemy import inspect

from td_service.persistence import (
    DefectSlaRow,
    FixEvidenceRow,
    IdempotencyRow,
    VerificationEvidenceRow,
)

revision: str = "0002_td_production_persistence"
down_revision: str | None = "0001_td_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create missing production tables and SLA breach columns."""
    bind = op.get_bind()
    FixEvidenceRow.__table__.create(bind=bind, checkfirst=True)
    VerificationEvidenceRow.__table__.create(bind=bind, checkfirst=True)
    IdempotencyRow.__table__.create(bind=bind, checkfirst=True)
    columns = {column["name"] for column in inspect(bind).get_columns(DefectSlaRow.__tablename__)}
    if "response_breached" not in columns:
        op.add_column(
            DefectSlaRow.__tablename__,
            DefectSlaRow.__table__.c.response_breached.copy(),
        )
    if "resolution_breached" not in columns:
        op.add_column(
            DefectSlaRow.__tablename__,
            DefectSlaRow.__table__.c.resolution_breached.copy(),
        )


def downgrade() -> None:
    """Remove the production persistence additions."""
    bind = op.get_bind()
    columns = {column["name"] for column in inspect(bind).get_columns(DefectSlaRow.__tablename__)}
    if "resolution_breached" in columns:
        op.drop_column(DefectSlaRow.__tablename__, "resolution_breached")
    if "response_breached" in columns:
        op.drop_column(DefectSlaRow.__tablename__, "response_breached")
    IdempotencyRow.__table__.drop(bind=bind, checkfirst=True)
    VerificationEvidenceRow.__table__.drop(bind=bind, checkfirst=True)
    FixEvidenceRow.__table__.drop(bind=bind, checkfirst=True)
