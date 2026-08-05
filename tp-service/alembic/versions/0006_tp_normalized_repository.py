"""Retire serialized UoW state and standardize runtime JSON payloads."""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0006_tp_normalized_repository"
down_revision: str | None = "0005_tp_repository_runtime"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _postgresql_binary_to_json(table: str, column: str) -> None:
    """Replace an unused binary payload with JSON without decoding pickle data."""
    bind = op.get_bind()
    count = bind.execute(sa.text(f"SELECT count(*) FROM {table}")).scalar_one()
    if count:
        raise RuntimeError(
            f"{table} contains legacy binary rows; migrate them with the "
            "approved offline conversion tool before upgrading"
        )
    op.alter_column(
        table,
        column,
        existing_type=sa.LargeBinary(),
        type_=sa.JSON(),
        postgresql_using=f"convert_from({column}, 'UTF8')::json",
        existing_nullable=False,
    )


def upgrade() -> None:
    """Remove the pickle state table and enforce JSON runtime contracts."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if bind.dialect.name == "postgresql":
        outbox_type = inspector.get_columns("tp_outbox_events")
        outbox_payload = next(item for item in outbox_type if item["name"] == "payload")
        if isinstance(outbox_payload["type"], sa.LargeBinary):
            _postgresql_binary_to_json("tp_outbox_events", "payload")
        idempotency_type = inspector.get_columns("tp_idempotency_records")
        response_payload = next(
            item for item in idempotency_type if item["name"] == "response_payload"
        )
        if isinstance(response_payload["type"], sa.LargeBinary):
            _postgresql_binary_to_json(
                "tp_idempotency_records",
                "response_payload",
            )
    if inspector.has_table("tp_unit_of_work_state"):
        op.drop_table("tp_unit_of_work_state")


def downgrade() -> None:
    """Recreate only the retired table shape; JSON payloads remain lossless."""
    op.create_table(
        "tp_unit_of_work_state",
        sa.Column("bucket", sa.String(length=64), primary_key=True),
        sa.Column("key", sa.String(length=512), primary_key=True),
        sa.Column("payload", sa.LargeBinary(), nullable=False),
    )
