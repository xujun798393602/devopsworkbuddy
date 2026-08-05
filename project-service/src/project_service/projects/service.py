"""Project creation application service."""

from __future__ import annotations

import hashlib
import json
import unicodedata
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import uuid4

from project_service.collaboration.models import ProjectMembership, Role
from project_service.persistence.uow import UnitOfWork
from project_service.projects.models import Project
from project_service.shared.audit import make_audit, make_outbox
from project_service.shared.errors import NotFoundError, ValidationError
from project_service.shared.idempotency import IdempotencyExecutor, StoredResponse
from project_service.shared.request_context import RequestContext

UnitOfWorkFactory = Callable[[], UnitOfWork]
_HASH_PREFIX = "v1\nPOST /api/v1/projects\n"


class ProjectService:
    """Coordinates project use cases and creates the Owner membership atomically."""

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        event_sink: Callable[[dict[str, object]], None] | None = None,
        idempotency: IdempotencyExecutor | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._idempotency = idempotency or IdempotencyExecutor()

    def create_project(
        self, payload: dict[str, object], context: RequestContext, idempotency_key: str
    ) -> StoredResponse:
        """Execute or replay a project creation request."""
        normalized = normalize_create_payload(payload, context.actor_id)
        with self._uow_factory() as uow:

            def write() -> StoredResponse:
                project = Project.create(
                    project_id=str(uuid4()),
                    business_no=uow.projects.next_business_no(),
                    name=normalized["name"],
                    description=normalized["description"],
                    owner_id=normalized["owner_id"],
                )
                uow.projects.add(project)
                # Flush the project first because the following independently mapped rows
                # reference it and SQLAlchemy cannot infer insert order without ORM relationships.
                uow.flush()
                now = datetime.now(UTC)
                owner = ProjectMembership(
                    str(uuid4()),
                    project.id,
                    project.owner_id,
                    Role.OWNER,
                    "active",
                    now,
                    context.actor_id,
                )
                uow.collaboration.add_membership(owner)
                audit = make_audit(
                    trace_id=context.trace_id,
                    actor_id=context.actor_id,
                    project_id=project.id,
                    resource_type="project",
                    resource_id=project.id,
                    action="project.created",
                    after={"owner_id": project.owner_id},
                    idempotency_key=idempotency_key,
                )
                event = make_outbox(
                    event_type="Project.Created.v1",
                    aggregate_type="project",
                    aggregate_id=project.id,
                    project_id=project.id,
                    payload={"project_id": project.id, "owner_id": project.owner_id},
                    trace_id=context.trace_id,
                )
                uow.audit.append(audit)
                uow.outbox.append(event)
                headers = {"ETag": f'"{project.version}"'}
                body = {"data": project.to_dict(), "meta": {"trace_id": context.trace_id}}
                return StoredResponse(201, body, headers)

            return self._idempotency.execute(
                uow,
                actor_id=context.actor_id,
                key=idempotency_key,
                operation="POST /api/v1/projects",
                path={},
                body=normalized,
                expected_version=None,
                handler=write,
            )

    def get_project(self, project_id: str, actor_id: str) -> Project:
        with self._uow_factory() as uow:
            if uow.collaboration.get_active_membership(project_id, actor_id) is None:
                raise NotFoundError()
            project = uow.projects.get(project_id)
        if project is None:
            raise NotFoundError()
        return project

    def list_projects(self, actor_id: str) -> list[Project]:
        with self._uow_factory() as uow:
            return uow.projects.list_for_actor(actor_id)


def normalize_create_payload(payload: dict[str, object], actor_id: str) -> dict[str, str]:
    allowed_fields = {"name", "description", "owner_id"}
    unknown_fields = sorted(payload.keys() - allowed_fields)
    if unknown_fields:
        raise ValidationError(
            "Request contains unknown fields",
            [{"field": field, "message": "Unknown field"} for field in unknown_fields],
        )
    errors: list[dict[str, str]] = []
    name_value = payload.get("name")
    description_value = payload.get("description", "")
    owner_value = payload.get("owner_id", actor_id)
    for field, value in (
        ("name", name_value),
        ("description", description_value),
        ("owner_id", owner_value),
    ):
        if not isinstance(value, str):
            errors.append({"field": field, "message": "Must be a string"})
    if errors:
        raise ValidationError("Request fields have invalid types", errors)
    name, description, owner_id = (
        _normalize(name_value),
        _normalize(description_value),
        _normalize(owner_value),
    )
    if not name:
        errors.append({"field": "name", "message": "Required"})
    elif len(name) > 120:
        errors.append({"field": "name", "message": "Must not exceed 120 characters"})
    if not owner_id:
        errors.append({"field": "owner_id", "message": "Must not be empty"})
    if errors:
        raise ValidationError("Request fields are invalid", errors)
    return {"name": name, "description": description, "owner_id": owner_id}


def create_request_hash(normalized_payload: dict[str, str]) -> str:
    canonical = json.dumps(
        normalized_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(f"{_HASH_PREFIX}{canonical}".encode()).hexdigest()


def _normalize(value: str) -> str:
    return unicodedata.normalize("NFC", value).strip()
