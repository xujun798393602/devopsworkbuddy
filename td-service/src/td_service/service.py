"""Defect application service with authorization and transactional outbox."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID, uuid4

from td_service.domain import Defect, DefectStatus, DomainError, FixEvidence, VerificationEvidence
from td_service.repository import PortalDefectSnapshot


class Authorizer(Protocol):
    def check(self, actor_id: UUID, project_id: UUID, action: str) -> bool: ...


class UnitOfWork(Protocol):
    defects: dict[tuple[UUID, UUID], Defect]
    outbox: list[dict[str, Any]]
    def commit(self) -> None: ...
    def rollback(self) -> None: ...
    def list_defects(self, project_id: UUID, offset: int, limit: int) -> list[Defect]: ...


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

    def patch(
        self,
        actor_id: UUID,
        project_id: UUID,
        defect_id: UUID,
        changes: dict[str, Any],
    ) -> Defect:
        """Apply governed field updates with an optimistic version bump.

        Only the mutable content fields may change; workflow state, assignee and
        verifier are owned by the transition actions. The aggregate invariants
        are re-run so a governed update cannot bypass them.

        Raises:
            PermissionError: When the authorizer denies ``defect:update``.
            DomainError: 404 when the defect is missing, 422 on an empty patch,
                an unknown field, or an unsupported severity.
        """
        if not self.authorizer.check(actor_id, project_id, "defect:update"):
            raise PermissionError("FORBIDDEN")
        defect = self.get(project_id, defect_id)
        if defect is None:
            raise DomainError("RESOURCE_NOT_FOUND", "Defect is not visible", 404)
        if not changes:
            raise DomainError("EMPTY_PATCH", "At least one field is required", 422)
        unknown = set(changes) - DEFECT_PATCHABLE_FIELDS
        if unknown:
            raise DomainError(
                "INVALID_PATCH_FIELD",
                f"Non-patchable fields: {', '.join(sorted(unknown))}",
                422,
            )
        before = defect.status
        if "title" in changes:
            defect.title = str(changes["title"])
        if "description" in changes:
            defect.description = str(changes["description"])
        if "severity" in changes:
            severity = str(changes["severity"])
            if severity not in {"blocker", "critical", "major", "minor", "trivial"}:
                raise DomainError("INVALID_SEVERITY", "Unsupported severity", 422)
            defect.severity = severity
        if "priority" in changes:
            defect.priority = str(changes["priority"])
        if "defect_type" in changes:
            defect.defect_type = str(changes["defect_type"])
        if "expected_result" in changes:
            defect.expected_result = str(changes["expected_result"])
        if "actual_result" in changes:
            defect.actual_result = str(changes["actual_result"])
        if "reproduction_steps" in changes:
            defect.reproduction_steps = tuple(map(str, changes["reproduction_steps"]))
        # Re-run the aggregate invariants: the snapshot was validated once at
        # construction and a governed update must not bypass them.
        defect.__post_init__()
        defect.version += 1
        defect.history.append(
            {
                "sequence_no": len(defect.history) + 1,
                "action": "patch",
                "actor_id": str(actor_id),
                "from": before.value,
                "to": defect.status.value,
                "reason": "field update",
            }
        )
        self.uow.outbox.append(
            {
                "event_type": "Defect.Patched",
                "event_version": 1,
                "project_id": str(project_id),
                "defect_id": str(defect.id),
                "business_no": defect.business_no,
                "status": defect.status.value,
                "severity": defect.severity,
                "version": defect.version,
            }
        )
        return defect

    def get_traceability_links(
        self, project_id: UUID, defect_id: UUID
    ) -> dict[str, list[Any]]:
        """Return the requirement/test-case traceability graph for a defect.

        P0 returns a structured empty graph (architecture §9.B.3) so the
        endpoint is reachable and the envelope is fixed; the link table is a P1
        follow-up.
        TODO(P1): populate ``nodes`` (requirement, test case) and ``edges`` from
        the defect traceability table.
        """
        defect = self.get(project_id, defect_id)
        if defect is None:
            raise DomainError("RESOURCE_NOT_FOUND", "Defect is not visible", 404)
        return {"nodes": [], "edges": []}


PORTAL_DEFECT_LIMIT_DEFAULT = 5
PORTAL_DEFECT_LIMIT_MAX = 50
DEFECT_LIST_LIMIT_DEFAULT = 20
DEFECT_LIST_LIMIT_MAX = 100

#: Fields a direct ``PATCH`` is allowed to mutate on a defect. Workflow state,
#: assignee and verifier remain owned by the explicit transition actions.
DEFECT_PATCHABLE_FIELDS: frozenset[str] = frozenset(
    {
        "title",
        "description",
        "severity",
        "priority",
        "defect_type",
        "expected_result",
        "actual_result",
        "reproduction_steps",
    }
)
PORTAL_STATUS_KEYS: tuple[str, ...] = ("new", "in_progress", "resolved", "closed")
PORTAL_SEVERITY_KEYS: tuple[str, ...] = ("critical", "high", "medium", "low")
PORTAL_CLOSED_STATUS = "closed"

# The nine-state defect workflow is folded into the four frozen portal buckets.
PORTAL_STATUS_MAP: dict[str, str] = {
    DefectStatus.NEW.value: "new",
    DefectStatus.ASSIGNED.value: "new",
    DefectStatus.REOPENED.value: "new",
    DefectStatus.IN_PROGRESS.value: "in_progress",
    DefectStatus.FIXED.value: "resolved",
    DefectStatus.PENDING_VERIFICATION.value: "resolved",
    DefectStatus.CLOSED.value: PORTAL_CLOSED_STATUS,
    DefectStatus.REJECTED.value: PORTAL_CLOSED_STATUS,
    DefectStatus.DUPLICATE.value: PORTAL_CLOSED_STATUS,
}

# The five-level severity scale is folded into the four frozen portal buckets.
PORTAL_SEVERITY_MAP: dict[str, str] = {
    "blocker": "critical",
    "critical": "critical",
    "major": "high",
    "minor": "medium",
    "trivial": "low",
}


class PortalRepository(Protocol):
    """Read-only port supplying batched portal projections."""

    def defects(
        self,
        project_ids: tuple[UUID, ...] | list[UUID],
        cross_project: bool = False,
    ) -> list[PortalDefectSnapshot]: ...


def portal_status(raw: str) -> str:
    """Map a workflow state onto a frozen portal bucket, defaulting to ``new``."""
    return PORTAL_STATUS_MAP.get(raw, "new")


def portal_severity(raw: str) -> str:
    """Map a severity level onto a frozen portal bucket, defaulting to ``medium``."""
    return PORTAL_SEVERITY_MAP.get(raw, "medium")


def portal_sla_breached(
    snapshot: PortalDefectSnapshot,
    status: str,
    now: datetime | None = None,
) -> bool:
    """Evaluate the SLA breach flag without mutating the persisted snapshot.

    Terminal defects keep their recorded verdict; live defects also consider due
    dates that elapsed since the last write so a read-only dashboard never
    reports a stale ``false``.
    """
    recorded = snapshot.response_breached or snapshot.resolution_breached
    if status == PORTAL_CLOSED_STATUS:
        return recorded
    current = now or datetime.now(UTC)
    response = snapshot.response_due_at is not None and (
        snapshot.first_responded_at is None and current > snapshot.response_due_at
    )
    resolution = snapshot.resolution_due_at is not None and (
        snapshot.resolved_at is None and current > snapshot.resolution_due_at
    )
    return recorded or response or resolution


def _portal_defect_item(
    snapshot: PortalDefectSnapshot,
    status: str,
    sla_breached: bool,
) -> dict[str, Any]:
    """Shape one defect item against the frozen portal contract."""
    return {
        "id": str(snapshot.id),
        "project_id": str(snapshot.project_id),
        "business_no": snapshot.business_no,
        "title": snapshot.title,
        "severity": portal_severity(snapshot.severity),
        "priority": snapshot.priority,
        "status": status,
        "sla_breached": sla_breached,
    }


@dataclass(slots=True)
class TdPortalService:
    """Aggregate read-only defect statistics for the platform dashboard."""

    repository: PortalRepository

    def summary(
        self,
        project_ids: tuple[UUID, ...] | list[UUID],
        actor_id: UUID | None = None,
        *,
        cross_project: bool = False,
        defect_limit: int = PORTAL_DEFECT_LIMIT_DEFAULT,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Return the frozen ``td_stats`` payload for the requested scope."""
        scope = tuple(dict.fromkeys(project_ids))
        snapshots = self.repository.defects(scope, cross_project)
        by_status = dict.fromkeys(PORTAL_STATUS_KEYS, 0)
        by_severity = dict.fromkeys(PORTAL_SEVERITY_KEYS, 0)
        breached = 0
        mine: list[dict[str, Any]] = []
        for snapshot in snapshots:
            status = portal_status(snapshot.status)
            by_status[status] += 1
            by_severity[portal_severity(snapshot.severity)] += 1
            sla_breached = portal_sla_breached(snapshot, status, now)
            if sla_breached:
                breached += 1
            is_open = status != PORTAL_CLOSED_STATUS
            if actor_id is not None and is_open and snapshot.assignee_id == actor_id:
                mine.append(_portal_defect_item(snapshot, status, sla_breached))
        return {
            "total": len(snapshots),
            "by_status": by_status,
            "by_severity": by_severity,
            "sla_breached": breached,
            "my_open_defects": {"count": len(mine), "items": mine[:defect_limit]},
        }
