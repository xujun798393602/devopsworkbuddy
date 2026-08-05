"""Requirement application service and transactional ports."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID, uuid4

from requirement_service.domain import Requirement, RequirementRevision, RequirementType


class Authorizer(Protocol):
    def check(self, actor_id: UUID, project_id: UUID, action: str) -> bool: ...


class UnitOfWork(Protocol):
    requirements: Any
    revisions: Any
    reviews: Any
    baselines: Any
    change_requests: Any
    outbox: Any

    def commit(self) -> None: ...

    def rollback(self) -> None: ...

    def get_idempotency(
        self, project_id: str, actor_id: str, key: str
    ) -> tuple[str, dict[str, Any], int] | None: ...

    def save_idempotency(
        self,
        project_id: str,
        actor_id: str,
        key: str,
        request_hash: str,
        response_body: dict[str, Any],
        response_status: int,
    ) -> None: ...


@dataclass(slots=True)
class RequirementService:
    """Coordinates pre-transaction authorization and local atomic writes."""

    uow: UnitOfWork
    authorizer: Authorizer

    def create(self, actor_id: UUID, project_id: UUID, payload: dict[str, Any]) -> Requirement:
        """Create an aggregate, immutable first revision, and outbox fact."""
        if not self.authorizer.check(actor_id, project_id, "requirement:create"):
            raise PermissionError("FORBIDDEN")
        requirement = Requirement(id=uuid4(), project_id=project_id,
            business_no=str(payload.get("business_no", f"REQ-{uuid4().hex[:8].upper()}")),
            title=str(payload.get("title", "")), type=RequirementType(str(payload.get("type", "user_story"))),
            owner_id=UUID(str(payload["owner_id"])), release_version_id=UUID(str(payload["release_version_id"])),
            description=str(payload.get("description", "")), priority=str(payload.get("priority", "p2")),
            acceptance_criteria=list(payload.get("acceptance_criteria", [])))
        revision = RequirementRevision.create(requirement.id, 1, requirement.snapshot())
        self.uow.requirements[(project_id, requirement.id)] = requirement
        self.uow.revisions[requirement.id] = [revision]
        self.uow.outbox.append({"event_type": "Requirement.Created", "event_version": 1,
            "project_id": str(project_id), "requirement_id": str(requirement.id),
            "business_no": requirement.business_no, "status": requirement.status.value,
            "version": requirement.version, "revision_no": 1, "revision_hash": revision.content_hash})
        return requirement

    def get(self, project_id: UUID, requirement_id: UUID) -> Requirement | None:
        """Load only through the project-scoped repository key."""
        return self.uow.requirements.get((project_id, requirement_id))
