"""Persistence-neutral idempotency execution primitives."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol, TypeVar

from project_service.idempotency.models import IdempotencyRecord
from project_service.shared.errors import ConflictError


@dataclass(slots=True)
class StoredResponse:
    """A complete replayable HTTP response."""

    status: int
    body: dict[str, Any] | None
    headers: dict[str, str]
    replayed: bool = False


class IdempotencyUnitOfWork(Protocol):
    """Minimum UoW contract needed by the executor."""

    idempotency: Any

    def commit(self) -> None: ...


T = TypeVar("T")


def canonical_request_hash(
    operation: str,
    path: dict[str, str],
    body: object,
    expected_version: int | None = None,
) -> str:
    """Hash the canonical API version, operation, path, body and If-Match value."""
    material = {
        "api_version": "v1",
        "operation": operation,
        "path": path,
        "body": body,
        "expected_version": expected_version,
    }
    canonical = json.dumps(
        material,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


class IdempotencyExecutor:
    """Run a write, audit, Outbox and response completion in one UoW transaction."""

    def execute(
        self,
        uow: IdempotencyUnitOfWork,
        *,
        actor_id: str,
        key: str,
        operation: str,
        path: dict[str, str],
        body: object,
        expected_version: int | None,
        handler: Callable[[], StoredResponse],
    ) -> StoredResponse:
        """Execute or replay one canonical write request."""
        scope = f"actor:{actor_id}|operation:{operation}"
        request_hash = canonical_request_hash(operation, path, body, expected_version)
        uow.idempotency.lock(scope, key)
        record = uow.idempotency.get(scope, key)
        if record is not None:
            return replay_or_conflict(record, request_hash)

        record = uow.idempotency.add_processing(scope, key, request_hash, operation)
        response = handler()
        uow.idempotency.complete(
            record,
            _resource_id(response.body),
            response.status,
            response.body,
            response.headers,
        )
        uow.commit()
        return response


def replay_or_conflict(record: IdempotencyRecord, request_hash: str) -> StoredResponse:
    """Return a completed replay or reject key reuse with another request."""
    if record.request_hash != request_hash:
        raise ConflictError(
            "Idempotency-Key was already used with a different request",
            "IDEMPOTENCY_KEY_CONFLICT",
        )
    if record.status != "completed":
        raise ConflictError("The original request is still processing", "IDEMPOTENCY_IN_PROGRESS")
    return StoredResponse(
        record.response_status or 200,
        record.response_body,
        record.response_headers or {},
        replayed=True,
    )


def _resource_id(body: dict[str, Any] | None) -> str | None:
    if not body:
        return None
    data = body.get("data")
    if isinstance(data, dict) and isinstance(data.get("id"), str):
        return data["id"]
    return None
