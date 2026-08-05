"""Requirement domain model with immutable revisions and explicit governance."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4


class DomainError(ValueError):
    """Business rule violation carrying a stable error code."""

    def __init__(self, code: str, detail: str, status: int = 409) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.status = status


class RequirementType(StrEnum):
    EPIC = "epic"
    FEATURE = "feature"
    USER_STORY = "user_story"
    FR = "fr"
    NFR = "nfr"
    AC = "ac"


class RequirementStatus(StrEnum):
    DRAFT = "draft"
    IN_REVIEW = "in_review"
    REJECTED = "rejected"
    APPROVED = "approved"
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELED = "canceled"


_ALLOWED_PARENT: dict[RequirementType, RequirementType | None] = {
    RequirementType.EPIC: None,
    RequirementType.FEATURE: RequirementType.EPIC,
    RequirementType.USER_STORY: RequirementType.FEATURE,
    RequirementType.FR: RequirementType.USER_STORY,
    RequirementType.NFR: RequirementType.USER_STORY,
    RequirementType.AC: RequirementType.USER_STORY,
}


def canonical_hash(value: dict[str, Any]) -> str:
    """Return a deterministic SHA-256 for an immutable JSON snapshot."""
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class RequirementRevision:
    """Immutable full snapshot of a requirement."""

    id: UUID
    requirement_id: UUID
    revision_no: int
    content_hash: str
    snapshot: dict[str, Any]

    @classmethod
    def create(cls, requirement_id: UUID, revision_no: int, snapshot: dict[str, Any]) -> RequirementRevision:
        copied = json.loads(json.dumps(snapshot))
        return cls(uuid4(), requirement_id, revision_no, canonical_hash(copied), copied)


@dataclass(slots=True)
class ReviewRound:
    """Append-only reviewer decisions for one frozen revision."""

    id: UUID
    round_no: int
    revision_id: UUID
    submitted_by: UUID
    reviewer_ids: tuple[UUID, ...]
    status: str = "open"
    decisions: list[dict[str, str]] = field(default_factory=list)

    def decide(self, reviewer_id: UUID, decision: str, comments: str = "") -> None:
        """Append a reviewer decision without overwriting history."""
        if self.status != "open" or reviewer_id not in self.reviewer_ids:
            raise DomainError("REVIEW_NOT_OPEN", "Reviewer cannot decide this review")
        if reviewer_id == self.submitted_by:
            raise DomainError("SELF_REVIEW_FORBIDDEN", "Submitter cannot review their own requirement", 403)
        if decision not in {"approved", "rejected", "changes_requested"}:
            raise DomainError("INVALID_DECISION", "Unsupported review decision", 422)
        self.decisions.append({"reviewer_id": str(reviewer_id), "decision": decision, "comments": comments})

    def close(self) -> str:
        """Close the round according to each reviewer's latest decision."""
        latest = {row["reviewer_id"]: row["decision"] for row in self.decisions}
        if "rejected" in latest.values() or "changes_requested" in latest.values():
            self.status = "rejected"
        elif "approved" in latest.values():
            self.status = "approved"
        else:
            raise DomainError("REVIEW_DECISION_REQUIRED", "At least one approval is required")
        return self.status


@dataclass(slots=True)
class Requirement:
    """Mutable requirement aggregate whose content is captured in revisions."""

    id: UUID
    project_id: UUID
    business_no: str
    title: str
    type: RequirementType
    owner_id: UUID
    release_version_id: UUID
    description: str = ""
    parent_id: UUID | None = None
    priority: str = "p2"
    status: RequirementStatus = RequirementStatus.DRAFT
    acceptance_criteria: list[dict[str, str]] = field(default_factory=list)
    current_revision: int = 1
    version: int = 1
    baseline_status: str = "unbaselined"

    def __post_init__(self) -> None:
        if not 1 <= len(self.title) <= 200 or len(self.description) > 20_000:
            raise DomainError("INVALID_REQUIREMENT", "Title or description length is invalid", 422)
        if self.priority not in {"p0", "p1", "p2", "p3"}:
            raise DomainError("INVALID_PRIORITY", "Unsupported priority", 422)
        if not 0 <= len(self.acceptance_criteria) <= 100:
            raise DomainError("INVALID_ACCEPTANCE_CRITERIA", "At most 100 acceptance criteria are allowed", 422)

    def snapshot(self) -> dict[str, Any]:
        """Return the complete content governed by revision immutability."""
        return {"title": self.title, "description": self.description, "type": self.type.value,
                "parent_id": str(self.parent_id) if self.parent_id else None, "priority": self.priority,
                "owner_id": str(self.owner_id), "release_version_id": str(self.release_version_id),
                "acceptance_criteria": self.acceptance_criteria}

    def set_parent(self, parent: Requirement | None, ancestors: set[UUID] | None = None) -> None:
        """Set a legal same-project parent while rejecting cycles."""
        expected = _ALLOWED_PARENT[self.type]
        if parent is None:
            if expected is not None:
                raise DomainError("PARENT_REQUIRED", f"{self.type.value} requires a parent")
            self.parent_id = None
            return
        if expected != parent.type:
            raise DomainError("INVALID_REQUIREMENT_HIERARCHY", "Parent type violates the fixed hierarchy")
        if parent.project_id != self.project_id:
            raise DomainError("RESOURCE_NOT_FOUND", "Parent requirement is not visible", 404)
        if parent.id == self.id or self.id in (ancestors or set()):
            raise DomainError("REQUIREMENT_CYCLE", "Requirement hierarchy cannot contain a cycle")
        self.parent_id = parent.id

    def transition(self, action: str, *, approved_review: bool = False, baselined: bool = False,
                   completion_evidence: bool = False, privileged: bool = False, reason: str = "") -> None:
        """Apply an explicit lifecycle action."""
        if action == "submit_review" and self.status in {RequirementStatus.DRAFT, RequirementStatus.REJECTED}:
            if self.type is not RequirementType.EPIC and not self.acceptance_criteria:
                raise DomainError("AC_REQUIRED", "Acceptance criteria are required before review", 422)
            self.status = RequirementStatus.IN_REVIEW
        elif action == "approve" and self.status is RequirementStatus.IN_REVIEW and approved_review:
            self.status = RequirementStatus.APPROVED
        elif action == "reject" and self.status is RequirementStatus.IN_REVIEW:
            self.status = RequirementStatus.REJECTED
        elif action == "return_to_draft" and self.status is RequirementStatus.REJECTED:
            self.status = RequirementStatus.DRAFT
        elif action == "activate" and self.status is RequirementStatus.APPROVED and baselined:
            self.status = RequirementStatus.ACTIVE
        elif action == "complete" and self.status is RequirementStatus.ACTIVE and completion_evidence:
            self.status = RequirementStatus.COMPLETED
        elif action == "cancel" and self.status is RequirementStatus.ACTIVE:
            self.status = RequirementStatus.CANCELED
        elif action == "reopen" and self.status is RequirementStatus.COMPLETED and privileged and reason.strip():
            self.status = RequirementStatus.ACTIVE
        else:
            raise DomainError("INVALID_STATE_TRANSITION", f"Action {action} is not allowed from {self.status.value}")
        self.version += 1


@dataclass(slots=True)
class Baseline:
    """Immutable requirement revision collection once active."""

    id: UUID
    project_id: UUID
    baseline_no: str
    release_version_id: UUID
    revision_refs: tuple[tuple[UUID, str], ...]
    status: str = "draft"
    version: int = 1

    def activate(self) -> None:
        """Activate the snapshot exactly once."""
        if self.status != "draft" or not self.revision_refs:
            raise DomainError("INVALID_BASELINE", "Only a non-empty draft baseline can be activated")
        self.status = "active"
        self.version += 1


@dataclass(slots=True)
class ChangeRequest:
    """Governed patch against a frozen base revision."""

    id: UUID
    requirement_id: UUID
    base_revision_id: UUID
    proposed_patch: dict[str, Any]
    status: str = "draft"
    version: int = 1

    ALLOWED_FIELDS = frozenset({"title", "description", "parent_id", "priority", "owner_id",
                                "release_version_id", "iteration_id", "acceptance_criteria", "tags"})

    def __post_init__(self) -> None:
        if not self.proposed_patch or not set(self.proposed_patch).issubset(self.ALLOWED_FIELDS):
            raise DomainError("INVALID_CHANGE_PATCH", "Change contains non-governed fields", 422)

    def transition(self, action: str) -> None:
        """Advance through the explicit governance state machine."""
        allowed = {("draft", "submit"): "in_review", ("in_review", "approve"): "approved",
                   ("in_review", "reject"): "rejected", ("approved", "apply"): "applied",
                   ("draft", "cancel"): "canceled", ("in_review", "cancel"): "canceled"}
        target = allowed.get((self.status, action))
        if target is None:
            raise DomainError("INVALID_STATE_TRANSITION", "Change request transition is invalid")
        self.status = target
        self.version += 1
