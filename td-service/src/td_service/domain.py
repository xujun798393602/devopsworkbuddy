"""Defect domain: explicit workflow, evidence, duplicate and SLA invariants."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any
from uuid import UUID


class DomainError(ValueError):
    """Stable business-rule failure."""

    def __init__(self, code: str, detail: str, status: int = 409) -> None:
        super().__init__(detail)
        self.code, self.detail, self.status = code, detail, status


class DefectStatus(StrEnum):
    NEW = "new"
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    FIXED = "fixed"
    PENDING_VERIFICATION = "pending_verification"
    CLOSED = "closed"
    REOPENED = "reopened"
    REJECTED = "rejected"
    DUPLICATE = "duplicate"


_SLA_HOURS = {
    "blocker": (0.25, 8),
    "critical": (1, 24),
    "major": (4, 72),
    "minor": (24, 240),
    "trivial": (48, 480),
}
_DEFECT_TYPES = {
    "functional",
    "performance",
    "security",
    "compatibility",
    "usability",
    "data",
    "configuration",
    "other",
}


@dataclass(frozen=True, slots=True)
class FixEvidence:
    """Immutable repair evidence reference."""

    type: str
    external_ref: str
    summary: str

    def __post_init__(self) -> None:
        if self.type not in {"mr", "commit", "patch", "other"} or not self.external_ref.strip() or not self.summary.strip():
            raise DomainError("INVALID_FIX_EVIDENCE", "Fix evidence type, reference and summary are required", 422)


@dataclass(frozen=True, slots=True)
class VerificationEvidence:
    """Immutable human verification evidence."""

    environment_ref: str
    conclusion: str
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.conclusion not in {"passed", "failed"} or not self.environment_ref.strip() or not self.evidence_refs:
            raise DomainError("INVALID_VERIFICATION_EVIDENCE", "Verification environment, conclusion and evidence are required", 422)


@dataclass(slots=True)
class SlaSnapshot:
    """Creation-time UTC continuous-time SLA policy snapshot."""

    policy_key: str
    policy_version: str
    response_due_at: datetime
    resolution_due_at: datetime
    first_responded_at: datetime | None = None
    resolved_at: datetime | None = None
    response_breached: bool = False
    resolution_breached: bool = False

    @classmethod
    def create(cls, severity: str, now: datetime | None = None) -> SlaSnapshot:
        current = now or datetime.now(UTC)
        if severity not in _SLA_HOURS:
            raise DomainError("INVALID_SEVERITY", "Unsupported severity", 422)
        response, resolution = _SLA_HOURS[severity]
        return cls(f"default-{severity}", "v1", current + timedelta(hours=response), current + timedelta(hours=resolution))

    def evaluate(self, now: datetime | None = None, terminal: bool = False) -> bool:
        """Evaluate breach flags without penalizing terminal records further."""
        current = now or datetime.now(UTC)
        if terminal:
            return self.response_breached or self.resolution_breached
        self.response_breached = self.first_responded_at is None and current > self.response_due_at
        self.resolution_breached = self.resolved_at is None and current > self.resolution_due_at
        return self.response_breached or self.resolution_breached


@dataclass(slots=True)
class Defect:
    """Defect aggregate; status can change only through named actions."""

    id: UUID
    project_id: UUID
    business_no: str
    title: str
    description: str
    severity: str
    priority: str
    defect_type: str
    reporter_id: UUID
    expected_result: str
    actual_result: str
    reproduction_steps: tuple[str, ...] = ()
    status: DefectStatus = DefectStatus.NEW
    assignee_id: UUID | None = None
    verifier_id: UUID | None = None
    affected_version_id: UUID | None = None
    fix_version_id: UUID | None = None
    root_cause: str = ""
    duplicate_of_id: UUID | None = None
    reopen_count: int = 0
    version: int = 1
    fix_evidence: list[FixEvidence] = field(default_factory=list)
    verification_evidence: list[VerificationEvidence] = field(default_factory=list)
    history: list[dict[str, Any]] = field(default_factory=list)
    sla: SlaSnapshot | None = None

    def __post_init__(self) -> None:
        if not 1 <= len(self.title) <= 200 or len(self.description) > 20_000:
            raise DomainError("INVALID_DEFECT", "Title or description length is invalid", 422)
        if (
            self.priority not in {"p0", "p1", "p2", "p3"}
            or self.severity not in _SLA_HOURS
            or self.defect_type not in _DEFECT_TYPES
        ):
            raise DomainError("INVALID_DEFECT_CLASSIFICATION", "Severity, priority or defect type is invalid", 422)
        if not self.expected_result.strip() or not self.actual_result.strip():
            raise DomainError("RESULTS_REQUIRED", "Expected and actual results are required", 422)
        if self.severity in {"blocker", "critical"} and not self.reproduction_steps:
            raise DomainError("REPRODUCTION_REQUIRED", "High severity defects require reproduction steps", 422)
        if len(self.reproduction_steps) > 50:
            raise DomainError("TOO_MANY_REPRODUCTION_STEPS", "At most 50 reproduction steps are allowed", 422)
        self.sla = self.sla or SlaSnapshot.create(self.severity)

    def _record(self, action: str, actor_id: UUID, before: DefectStatus, reason: str = "") -> None:
        self.version += 1
        self.history.append({"sequence_no": len(self.history) + 1, "action": action, "actor_id": str(actor_id), "from": before.value, "to": self.status.value, "reason": reason})

    def transition(self, action: str, actor_id: UUID, *, privileged: bool = False, assignee_id: UUID | None = None,
                   verifier_id: UUID | None = None, reason: str = "", fix_version_id: UUID | None = None,
                   fix_evidence: FixEvidence | None = None, verification: VerificationEvidence | None = None,
                   root_cause: str = "", duplicate_of_id: UUID | None = None, duplicate_ancestors: set[UUID] | None = None) -> None:
        """Execute one explicit state action and append history."""
        before = self.status
        if action == "assign" and before in {DefectStatus.NEW, DefectStatus.REOPENED} and assignee_id:
            self.assignee_id, self.status = assignee_id, DefectStatus.ASSIGNED
        elif action == "start" and before is DefectStatus.ASSIGNED and (privileged or actor_id == self.assignee_id):
            self.status = DefectStatus.IN_PROGRESS
            assert self.sla is not None
            self.sla.first_responded_at = self.sla.first_responded_at or datetime.now(UTC)
        elif action == "reject" and before is DefectStatus.NEW and privileged and reason.strip():
            self.status = DefectStatus.REJECTED
        elif action == "mark_fixed" and before is DefectStatus.IN_PROGRESS and fix_version_id and fix_evidence:
            self.fix_version_id = fix_version_id
            self.fix_evidence.append(fix_evidence)
            self.status = DefectStatus.FIXED
        elif action == "submit_verification" and before is DefectStatus.FIXED and verifier_id:
            if not self.fix_version_id or not self.fix_evidence:
                raise DomainError("FIX_EVIDENCE_REQUIRED", "Fix version and evidence are required")
            self.verifier_id, self.status = verifier_id, DefectStatus.PENDING_VERIFICATION
        elif action == "verify_close" and before is DefectStatus.PENDING_VERIFICATION and verification and verification.conclusion == "passed" and root_cause.strip():
            if actor_id != self.verifier_id and not privileged:
                raise DomainError("FORBIDDEN", "Only verifier or administrator may close", 403)
            self.root_cause = root_cause
            self.verification_evidence.append(verification)
            self.status = DefectStatus.CLOSED
            assert self.sla is not None
            self.sla.resolved_at = datetime.now(UTC)
        elif action == "verify_fail" and before is DefectStatus.PENDING_VERIFICATION and verification and verification.conclusion == "failed":
            self.verification_evidence.append(verification)
            self.status = DefectStatus.REOPENED
            self.reopen_count += 1
        elif action == "manual_reopen" and before is DefectStatus.CLOSED and (privileged or actor_id in {self.verifier_id, self.reporter_id}) and reason.strip():
            self.status = DefectStatus.REOPENED
            self.reopen_count += 1
        elif action == "mark_duplicate" and before in {DefectStatus.NEW, DefectStatus.ASSIGNED, DefectStatus.IN_PROGRESS} and privileged and duplicate_of_id and reason.strip():
            if duplicate_of_id == self.id or self.id in (duplicate_ancestors or set()):
                raise DomainError("DUPLICATE_CYCLE", "Duplicate chain cannot contain a cycle")
            self.duplicate_of_id, self.status = duplicate_of_id, DefectStatus.DUPLICATE
        else:
            raise DomainError("INVALID_STATE_TRANSITION", f"Action {action} is not allowed from {before.value}")
        self._record(action, actor_id, before, reason)
