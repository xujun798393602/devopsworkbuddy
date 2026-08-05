"""Factories for reliable audit and outbox records."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4


@dataclass(frozen=True, slots=True)
class AuditRecord:
    id: str
    occurred_at: datetime
    trace_id: str
    actor_id: str
    project_id: str
    resource_type: str
    resource_id: str
    action: str
    result: str = "success"
    before: dict[str, Any] = field(default_factory=dict)
    after: dict[str, Any] = field(default_factory=dict)
    reason: str | None = None
    source: str = "api"
    idempotency_key: str | None = None


@dataclass(frozen=True, slots=True)
class OutboxEvent:
    id: str
    event_type: str
    event_version: int
    aggregate_type: str
    aggregate_id: str
    project_id: str
    payload: dict[str, Any]
    trace_id: str
    occurred_at: datetime


def make_audit(
    *,
    trace_id: str,
    actor_id: str,
    project_id: str,
    resource_type: str,
    resource_id: str,
    action: str,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    reason: str | None = None,
    idempotency_key: str | None = None,
) -> AuditRecord:
    """Create an immutable successful audit record."""
    return AuditRecord(
        str(uuid4()),
        datetime.now(UTC),
        trace_id,
        actor_id,
        project_id,
        resource_type,
        resource_id,
        action,
        before=before or {},
        after=after or {},
        reason=reason,
        idempotency_key=idempotency_key,
    )


def make_outbox(
    *,
    event_type: str,
    aggregate_type: str,
    aggregate_id: str,
    project_id: str,
    payload: dict[str, Any],
    trace_id: str,
) -> OutboxEvent:
    """Create a pending version-one outbox event."""
    return OutboxEvent(
        str(uuid4()),
        event_type,
        1,
        aggregate_type,
        aggregate_id,
        project_id,
        payload,
        trace_id,
        datetime.now(UTC),
    )
