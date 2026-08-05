from datetime import UTC, datetime
from uuid import uuid4

from project_service.projects.models import Project
from project_service.shared.request_context import RequestContext


def project_created_event(project: Project, context: RequestContext) -> dict[str, object]:
    return {
        "event_id": str(uuid4()),
        "event_type": "Project.Created",
        "event_version": 1,
        "occurred_at": datetime.now(UTC).isoformat(),
        "producer": "project-service",
        "trace_id": context.trace_id,
        "project_id": project.id,
        "actor": {"type": "user", "id": context.actor_id},
        "aggregate": {"type": "project", "id": project.id, "version": project.version},
        "data": {"business_no": project.business_no, "name": project.name},
        "security": {"classification": "internal"},
    }
