from typing import Any, Protocol

from project_service.idempotency.models import IdempotencyRecord


class IdempotencyRepository(Protocol):
    """Generic response replay persistence contract."""

    def lock(self, scope: str, key: str) -> None: ...
    def get(self, scope: str, key: str) -> IdempotencyRecord | None: ...
    def add_processing(
        self, scope: str, key: str, request_hash: str, operation: str = "POST /api/v1/projects"
    ) -> IdempotencyRecord: ...
    def complete(
        self,
        record: IdempotencyRecord,
        resource_id: str | None,
        status: int,
        body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None: ...
