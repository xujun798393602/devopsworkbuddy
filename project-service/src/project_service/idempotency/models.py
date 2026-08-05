from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class IdempotencyRecord:
    """Persistence-neutral, complete replay idempotency record."""

    scope: str
    idempotency_key: str
    request_hash: str
    status: str
    operation: str = "POST /api/v1/projects"
    response_status: int | None = None
    resource_id: str | None = None
    response_body: dict[str, Any] | None = None
    response_headers: dict[str, str] | None = None
    created_at: datetime | None = None
    completed_at: datetime | None = None
    expires_at: datetime | None = None
