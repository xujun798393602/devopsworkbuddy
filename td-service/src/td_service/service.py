"""Defect application service with authorization and transactional outbox."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID, uuid4

from td_service.domain import Defect, FixEvidence, VerificationEvidence


class Authorizer(Protocol):
    def check(self, actor_id: UUID, project_id: UUID, action: str) -> bool: ...


class UnitOfWork(Protocol):
    defects: dict[tuple[UUID, UUID], Defect]
    outbox: list[dict[str, Any]]
    def commit(self) -> None: ...
    def rollback(self) -> None: ...


@dataclass(slots=True)
class DefectService:
    """Coordinates defect commands without cross-service transactions."""

    uow: UnitOfWork
    authorizer: Authorizer

    def create(self, actor_id: UUID, project_id: UUID, payload: dict[str, Any]) -> Defect:
        """Create a defect and SLA snapshot with one outbox fact."""
        if not self.authorizer.check(actor_id, project_id, "defect:create"):
            raise PermissionError("FORBIDDEN")
        defect = Defect(
            id=uuid4(), project_id=project_id,
            business_no=str(payload.get("business_no", f"TD-{uuid4().hex[:8].upper()}")),
            title=str(payload.get("title", "")), description=str(payload.get("description", "")),
            severity=str(payload.get("severity", "major")), priority=str(payload.get("priority", "p2")),
            defect_type=str(payload.get("defect_type", "functional")), reporter_id=actor_id,
            expected_result=str(payload.get("expected_result", "")), actual_result=str(payload.get("actual_result", "")),
            reproduction_steps=tuple(map(str, payload.get("reproduction_steps", []))),
        )
        self.uow.defects[(project_id, defect.id)] = defect
        self.uow.outbox.append({"event_type": "Defect.Created", "event_version": 1, "project_id": str(project_id), "defect_id": str(defect.id), "business_no": defect.business_no, "status": defect.status.value, "severity": defect.severity, "version": 1})
        return defect

    def get(self, project_id: UUID, defect_id: UUID) -> Defect | None:
        """Get a project-scoped defect."""
        return self.uow.defects.get((project_id, defect_id))

    def transition(
        self,
        actor_id: UUID,
        project_id: UUID,
        defect_id: UUID,
        *,
        action: str,
        privileged: bool = False,
        assignee_id: UUID | None = None,
        verifier_id: UUID | None = None,
        reason: str = "",
        fix_version_id: UUID | None = None,
        fix_evidence: FixEvidence | None = None,
        verification: VerificationEvidence | None = None,
        root_cause: str = "",
        duplicate_of_id: UUID | None = None,
    ) -> Defect:
        """Authorize and atomically execute an explicit defect action."""
        if not self.authorizer.check(actor_id, project_id, f"defect:{action}"):
            raise PermissionError("FORBIDDEN")
        defect = self.get(project_id, defect_id)
        if defect is None:
            raise KeyError("RESOURCE_NOT_FOUND")
        ancestors: set[UUID] = set()
        if duplicate_of_id is not None:
            master = self.get(project_id, duplicate_of_id)
            if master is None:
                raise KeyError("RESOURCE_NOT_FOUND")
            duplicate_ancestors = getattr(self.uow, "duplicate_ancestors", None)
            ancestors = duplicate_ancestors(project_id, duplicate_of_id) if duplicate_ancestors else {duplicate_of_id}
        defect.transition(
            action,
            actor_id,
            privileged=privileged,
            assignee_id=assignee_id,
            verifier_id=verifier_id,
            reason=reason,
            fix_version_id=fix_version_id,
            fix_evidence=fix_evidence,
            verification=verification,
            root_cause=root_cause,
            duplicate_of_id=duplicate_of_id,
            duplicate_ancestors=ancestors,
        )
        event_name = {
            "assign": "Defect.Assigned",
            "mark_fixed": "Defect.Fixed",
            "submit_verification": "Defect.PendingVerification",
            "verify_close": "Defect.Closed",
            "verify_fail": "Defect.Reopened",
            "manual_reopen": "Defect.Reopened",
            "mark_duplicate": "Defect.DuplicateLinked",
        }.get(action, "Defect.Changed")
        self.uow.outbox.append(
            {
                "event_type": event_name,
                "event_version": 1,
                "project_id": str(project_id),
                "defect_id": str(defect.id),
                "business_no": defect.business_no,
                "status": defect.status.value,
                "severity": defect.severity,
                "version": defect.version,
                "assignee_id": str(defect.assignee_id) if defect.assignee_id else None,
                "verifier_id": str(defect.verifier_id) if defect.verifier_id else None,
                "reopen_count": defect.reopen_count,
            }
        )
        return defect
