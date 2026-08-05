"""Audit event validation and append-only ingestion."""

from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4

from audit_service.records.models import AuditRecord
from audit_service.records.redaction import validate_and_redact


class AuditRepository(Protocol):
    """Persistence contract required by audit ingestion."""

    def append(self, record: AuditRecord) -> AuditRecord:
        """Append or replay an audit record."""


class AuditIngestService:
    """Validate, redact, and persist immutable audit events."""

    def __init__(self, repo: AuditRepository) -> None:
        self.repo = repo

    def ingest(
        self, event: dict[str, object], caller_scopes: set[str]
    ) -> AuditRecord:
        """Ingest one authorized event after sensitive-data validation."""
        if "audit:ingest" not in caller_scopes:
            raise PermissionError("INGEST_FORBIDDEN")
        clean = validate_and_redact(event)
        actor = clean["actor"]
        resource = clean["resource"]
        return self.repo.append(
            AuditRecord(
                id=str(uuid4()),
                event_id=str(clean["event_id"]),
                occurred_at=datetime.fromisoformat(str(clean["occurred_at"])),
                ingested_at=datetime.now(UTC),
                trace_id=str(clean["trace_id"]),
                actor_id=str(actor["id"]),
                actor_type=str(actor["type"]),
                project_id=(
                    None
                    if clean.get("project_id") is None
                    else str(clean["project_id"])
                ),
                resource_type=str(resource["type"]),
                resource_id=str(resource["id"]),
                action=str(clean["action"]),
                result=str(clean["result"]),
                source=str(clean["source"]),
                metadata=dict(clean.get("metadata", {})),
                classification=str(clean.get("classification", "internal")),
            )
        )
