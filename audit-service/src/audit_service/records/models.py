from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class AuditRecord:
    id: str
    event_id: str
    occurred_at: datetime
    ingested_at: datetime
    trace_id: str
    actor_id: str
    actor_type: str
    project_id: str | None
    resource_type: str
    resource_id: str
    action: str
    result: str
    source: str
    metadata: dict[str, object]
    classification: str
