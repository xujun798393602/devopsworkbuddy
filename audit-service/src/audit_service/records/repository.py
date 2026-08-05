"""Append-only repository: deliberately exposes no update or delete."""
from audit_service.records.models import AuditRecord


class InMemoryAuditRepository:
    def __init__(self) -> None:
        self.records: dict[str, AuditRecord] = {}
        self.events: set[str] = set()

    def append(self, record: AuditRecord) -> AuditRecord:
        if record.event_id in self.events:
            return next(
                item
                for item in self.records.values()
                if item.event_id == record.event_id
            )
        self.records[record.id] = record
        self.events.add(record.event_id)
        return record

    def list(self) -> list[AuditRecord]:
        return sorted(
            self.records.values(),
            key=lambda item: (item.occurred_at, item.id),
            reverse=True,
        )
