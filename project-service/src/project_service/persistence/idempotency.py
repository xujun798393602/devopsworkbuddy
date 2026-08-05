import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from project_service.idempotency.models import IdempotencyRecord
from project_service.persistence.tables import IdempotencyRecordRow

_ADVISORY_SEED = 74839201


class SqlAlchemyIdempotencyRepository:
    """PostgreSQL transaction-locking generic idempotency repository."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def lock(self, scope: str, key: str) -> None:
        if self._session.bind is not None and self._session.bind.dialect.name == "postgresql":
            lock_material = json.dumps([scope, key], ensure_ascii=False, separators=(",", ":"))
            self._session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:material, :seed))"),
                {"material": lock_material, "seed": _ADVISORY_SEED},
            )

    def get(self, scope: str, key: str) -> IdempotencyRecord | None:
        row = self._session.scalar(
            select(IdempotencyRecordRow).where(
                IdempotencyRecordRow.scope == scope, IdempotencyRecordRow.idempotency_key == key
            )
        )
        return _to_domain(row) if row else None

    def add_processing(
        self, scope: str, key: str, request_hash: str, operation: str = "POST /api/v1/projects"
    ) -> IdempotencyRecord:
        row = IdempotencyRecordRow(
            scope=scope,
            idempotency_key=key,
            request_hash=request_hash,
            operation=operation,
            status="processing",
        )
        self._session.add(row)
        self._session.flush()
        return IdempotencyRecord(scope, key, request_hash, "processing", operation=operation)

    def complete(
        self,
        record: IdempotencyRecord,
        resource_id: str | None,
        status: int,
        body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        row = self._session.scalar(
            select(IdempotencyRecordRow).where(
                IdempotencyRecordRow.scope == record.scope,
                IdempotencyRecordRow.idempotency_key == record.idempotency_key,
            )
        )
        if row is None:
            raise RuntimeError("Idempotency record disappeared during transaction")
        row.status = "completed"
        row.resource_id = UUID(resource_id) if resource_id else None
        row.response_status = status
        row.response_body = body
        row.response_headers = headers or {}
        row.completed_at = datetime.now(UTC)
        record.status = "completed"
        record.resource_id = resource_id
        record.response_status = status
        record.response_body = body
        record.response_headers = headers or {}
        record.completed_at = row.completed_at


def _to_domain(row: IdempotencyRecordRow) -> IdempotencyRecord:
    return IdempotencyRecord(
        row.scope,
        row.idempotency_key,
        row.request_hash,
        row.status,
        operation=row.operation,
        response_status=row.response_status,
        resource_id=str(row.resource_id) if row.resource_id else None,
        response_body=row.response_body,
        response_headers=row.response_headers,
        created_at=row.created_at,
        completed_at=row.completed_at,
        expires_at=row.expires_at,
    )
