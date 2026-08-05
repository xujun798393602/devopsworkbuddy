"""Create TD service private schema."""
from collections.abc import Sequence

from alembic import op

from td_service.persistence import Base

revision: str = "0001_td_baseline"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
