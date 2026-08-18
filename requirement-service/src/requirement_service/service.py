"""Requirement application service and transactional ports."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID, uuid4

from requirement_service.domain import (
    Baseline,
    ChangeRequest,
    DomainError,
    Requirement,
    RequirementRevision,
    RequirementStatus,
    RequirementType,
    ReviewRound,
)

PORTAL_REVIEW_LIMIT_DEFAULT = 5
PORTAL_REVIEW_LIMIT_MAX = 50

#: Cursor page bounds for ``GET /api/v1/projects/{id}/requirements``.
REQUIREMENT_LIST_LIMIT_DEFAULT = 20
REQUIREMENT_LIST_LIMIT_MAX = 100

#: Lifecycle actions accepted by ``POST .../requirements/{id}/transitions``.
#: The tuple mirrors :meth:`requirement_service.domain.Requirement.transition`;
#: only ``reopen`` makes ``reason`` mandatory (the domain requires
#: ``privileged and reason.strip()``), every other action treats it as audit
#: metadata.
REQUIREMENT_ACTIONS: tuple[str, ...] = (
    "submit_review",
    "approve",
    "reject",
    "return_to_draft",
    "activate",
    "complete",
    "cancel",
    "reopen",
)

#: Actions that must carry a non-empty ``reason``.
REASON_REQUIRED_ACTIONS: frozenset[str] = frozenset({"reopen"})

#: Governed fields that map onto a real ``Requirement`` attribute and can be
#: written by ``PATCH`` or by applying a change request.
PATCHABLE_FIELDS: frozenset[str] = frozenset(
    {
        "title",
        "description",
        "priority",
        "owner_id",
        "release_version_id",
        "parent_id",
        "acceptance_criteria",
    }
)

#: Fields listed in :attr:`ChangeRequest.ALLOWED_FIELDS` that the aggregate and
#: the ``requirements`` table cannot store yet (``tags``, ``iteration_id``).
#: They are rejected up front instead of being accepted into a change request
#: that could never be applied.
#: TODO(P1): add the columns plus a migration, then move them into
#: ``PATCHABLE_FIELDS``.
UNPERSISTED_GOVERNED_FIELDS: frozenset[str] = (
    ChangeRequest.ALLOWED_FIELDS - PATCHABLE_FIELDS
)

#: Review decisions accepted by :meth:`ReviewRound.decide`.
REVIEW_DECISIONS: frozenset[str] = frozenset(
    {"approved", "rejected", "changes_requested"}
)

#: Change request actions accepted by :meth:`ChangeRequest.transition`.
CHANGE_REQUEST_ACTIONS: tuple[str, ...] = (
    "submit",
    "approve",
    "reject",
    "apply",
    "cancel",
)

#: Frozen portal contract keys (architecture §3.1). The domain lifecycle is richer
#: than the dashboard vocabulary, so terminal states collapse into ``archived`` and
#: ``active`` (approved + baselined, in delivery) reports as ``approved``.
PORTAL_STATUS_KEYS: tuple[str, ...] = ("draft", "reviewing", "approved", "rejected", "archived")

PORTAL_STATUS_MAP: dict[RequirementStatus, str] = {
    RequirementStatus.DRAFT: "draft",
    RequirementStatus.IN_REVIEW: "reviewing",
    RequirementStatus.APPROVED: "approved",
    RequirementStatus.ACTIVE: "approved",
    RequirementStatus.REJECTED: "rejected",
    RequirementStatus.COMPLETED: "archived",
    RequirementStatus.CANCELED: "archived",
}


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

    def list_requirements(
        self, project_id: UUID, offset: int, limit: int
    ) -> list[Requirement]: ...

    def portal_requirements(
        self, project_ids: tuple[str, ...], cross_project: bool
    ) -> list[Requirement]: ...

    def portal_active_baseline_total(
        self, project_ids: tuple[str, ...], cross_project: bool
    ) -> int: ...

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

    # ------------------------------------------------------------------
    # Listing
    # ------------------------------------------------------------------

    def list_requirements(
        self, project_id: UUID, *, offset: int, limit: int
    ) -> list[Requirement]:
        """Return one deterministic page of project requirements.

        The HTTP adapter owns cursor encoding and asks for ``limit + 1`` rows so
        it can decide whether another page exists without a second query.

        Args:
            project_id: Project scope; rows outside it are never visible.
            offset: Number of rows to skip, decoded from the opaque cursor.
            limit: Maximum number of rows to return.

        Returns:
            Requirements ordered by ``(business_no, id)`` so cursors stay stable.
        """
        return self.uow.list_requirements(project_id, offset, limit)

    # ------------------------------------------------------------------
    # Field updates and lifecycle
    # ------------------------------------------------------------------

    def patch(
        self,
        actor_id: UUID,
        project_id: UUID,
        requirement_id: UUID,
        changes: dict[str, Any],
    ) -> tuple[Requirement, ChangeRequest | None]:
        """Update governed fields, or open a change request once baselined.

        An unbaselined requirement is edited in place: the fields are applied,
        the aggregate invariants re-run, and a new immutable revision is frozen.
        A baselined requirement is protected by governance, so the same body is
        turned into a ``draft`` change request instead and the aggregate is left
        untouched until the change request is applied.

        Args:
            actor_id: Gateway-verified identity performing the update.
            project_id: Project scope of the requirement.
            requirement_id: Target requirement.
            changes: Governed field subset to write.

        Returns:
            A ``(requirement, change_request)`` pair. ``change_request`` is
            ``None`` when the update was applied directly.

        Raises:
            PermissionError: When the authorizer denies the action.
            DomainError: When the requirement is missing (404) or the patch is
                empty / contains non-governed fields (422).
        """
        if not self.authorizer.check(actor_id, project_id, "requirement:update"):
            raise PermissionError("FORBIDDEN")
        requirement = self._require(project_id, requirement_id)
        self._assert_governed_fields(changes)
        if requirement.baseline_status == "baselined":
            revision = self._latest_revision(requirement_id)
            change = ChangeRequest(uuid4(), requirement.id, revision.id, dict(changes))
            self.uow.change_requests[(project_id, change.id)] = change
            self.uow.outbox.append(
                {
                    "event_type": "Requirement.ChangeRequested",
                    "event_version": 1,
                    "project_id": str(project_id),
                    "requirement_id": str(requirement.id),
                    "change_request_id": str(change.id),
                    "base_revision_id": str(change.base_revision_id),
                    "status": change.status,
                    "version": change.version,
                }
            )
            return requirement, change
        self._apply_fields(project_id, requirement, changes)
        self.uow.requirements[(project_id, requirement.id)] = requirement
        self.uow.outbox.append(
            {
                "event_type": "Requirement.Updated",
                "event_version": 1,
                "project_id": str(project_id),
                "requirement_id": str(requirement.id),
                "business_no": requirement.business_no,
                "status": requirement.status.value,
                "version": requirement.version,
                "revision_no": requirement.current_revision,
                "fields": sorted(changes),
            }
        )
        return requirement, None

    def transition(
        self,
        actor_id: UUID,
        project_id: UUID,
        requirement_id: UUID,
        *,
        action: str,
        approved_review: bool = False,
        baselined: bool = False,
        completion_evidence: bool = False,
        privileged: bool = False,
        reason: str = "",
    ) -> Requirement:
        """Apply one explicit lifecycle action to a requirement.

        The evidence flags are supplied by the caller exactly as designed in the
        architecture (§9.A.3).
        TODO(P1): derive ``approved_review`` from the closed review round and
        ``baselined`` from the active baseline instead of trusting the client.

        Args:
            actor_id: Gateway-verified identity performing the action.
            project_id: Project scope of the requirement.
            requirement_id: Target requirement.
            action: One of :data:`REQUIREMENT_ACTIONS`.
            approved_review: Evidence that the review round approved the change.
            baselined: Evidence that the requirement is covered by a baseline.
            completion_evidence: Evidence that delivery is complete.
            privileged: Caller holds the privileged role (required by ``reopen``).
            reason: Audit reason; mandatory for ``reopen``.

        Returns:
            The updated requirement with an incremented ``version``.

        Raises:
            PermissionError: When the authorizer denies the action.
            DomainError: When the requirement is missing (404) or the action is
                illegal from the current state (409/422).
        """
        if not self.authorizer.check(actor_id, project_id, f"requirement:{action}"):
            raise PermissionError("FORBIDDEN")
        requirement = self._require(project_id, requirement_id)
        before = requirement.status.value
        requirement.transition(
            action,
            approved_review=approved_review,
            baselined=baselined,
            completion_evidence=completion_evidence,
            privileged=privileged,
            reason=reason,
        )
        self.uow.requirements[(project_id, requirement.id)] = requirement
        self.uow.outbox.append(
            {
                "event_type": "Requirement.StatusChanged",
                "event_version": 1,
                "project_id": str(project_id),
                "requirement_id": str(requirement.id),
                "business_no": requirement.business_no,
                "action": action,
                "from_status": before,
                "status": requirement.status.value,
                "version": requirement.version,
                "reason": reason,
            }
        )
        return requirement

    # ------------------------------------------------------------------
    # Review rounds
    # ------------------------------------------------------------------

    def list_reviews(self, project_id: UUID, requirement_id: UUID) -> list[ReviewRound]:
        """Return every review round of a requirement ordered by round number."""
        self._require(project_id, requirement_id)
        return self._reviews_for(requirement_id)

    def create_review(
        self,
        actor_id: UUID,
        project_id: UUID,
        requirement_id: UUID,
        *,
        reviewer_ids: tuple[UUID, ...],
        note: str = "",
    ) -> ReviewRound:
        """Open a review round against the requirement's latest frozen revision.

        ``note`` is carried on the outbox event because :class:`ReviewRound` has
        no note column; it is therefore auditable but not queryable.
        TODO(P1): persist the note once the review table gains a column.

        Raises:
            DomainError: 404 when the requirement is missing, 422 when no
                reviewer is supplied, 403 when the submitter reviews itself.
        """
        if not self.authorizer.check(actor_id, project_id, "requirement:review"):
            raise PermissionError("FORBIDDEN")
        self._require(project_id, requirement_id)
        reviewers = tuple(dict.fromkeys(reviewer_ids))
        if not reviewers:
            raise DomainError(
                "REVIEWERS_REQUIRED", "At least one reviewer is required", 422
            )
        if actor_id in reviewers:
            raise DomainError(
                "SELF_REVIEW_FORBIDDEN",
                "Submitter cannot review their own requirement",
                403,
            )
        revision = self._latest_revision(requirement_id)
        review = ReviewRound(
            uuid4(),
            len(self._reviews_for(requirement_id)) + 1,
            revision.id,
            actor_id,
            reviewers,
        )
        self.uow.reviews[review.id] = review
        self.uow.outbox.append(
            {
                "event_type": "Requirement.ReviewRequested",
                "event_version": 1,
                "project_id": str(project_id),
                "requirement_id": str(requirement_id),
                "review_id": str(review.id),
                "round_no": review.round_no,
                "revision_id": str(review.revision_id),
                "reviewer_ids": [str(item) for item in reviewers],
                "note": note,
            }
        )
        return review

    def decide_review(
        self,
        actor_id: UUID,
        project_id: UUID,
        requirement_id: UUID,
        review_id: UUID,
        *,
        reviewer_id: UUID,
        decision: str,
        comments: str = "",
    ) -> ReviewRound:
        """Append one reviewer decision and close the round when complete.

        A round closes as soon as every invited reviewer has decided, so the
        ``approve``/``reject`` lifecycle action has a terminal verdict to rely on.

        Raises:
            DomainError: 404 when the round is not visible, 403 for self review
                or for deciding on somebody else's behalf, 409 when the round is
                already closed, 422 for an unsupported decision.
        """
        if not self.authorizer.check(actor_id, project_id, "requirement:review"):
            raise PermissionError("FORBIDDEN")
        self._require(project_id, requirement_id)
        review = self._review_of(requirement_id, review_id)
        if reviewer_id != actor_id:
            raise DomainError(
                "FORBIDDEN", "A reviewer may only submit their own decision", 403
            )
        review.decide(reviewer_id, decision, comments)
        decided = {row["reviewer_id"] for row in review.decisions}
        if decided >= {str(item) for item in review.reviewer_ids}:
            review.close()
        self.uow.reviews[review.id] = review
        self.uow.outbox.append(
            {
                "event_type": "Requirement.ReviewDecided",
                "event_version": 1,
                "project_id": str(project_id),
                "requirement_id": str(requirement_id),
                "review_id": str(review.id),
                "reviewer_id": str(reviewer_id),
                "decision": decision,
                "status": review.status,
            }
        )
        return review

    # ------------------------------------------------------------------
    # Baselines
    # ------------------------------------------------------------------

    def list_baselines(self, project_id: UUID) -> list[Baseline]:
        """Return every baseline of a project ordered by baseline number."""
        values = [
            value
            for (scope, _), value in self.uow.baselines.items()
            if scope == project_id
        ]
        values.sort(key=lambda item: (item.baseline_no, str(item.id)))
        return values

    def get_baseline(self, project_id: UUID, baseline_id: UUID) -> Baseline:
        """Load a project-scoped baseline or fail with 404."""
        value = self.uow.baselines.get((project_id, baseline_id))
        if value is None:
            raise DomainError("RESOURCE_NOT_FOUND", "Baseline is not visible", 404)
        return value

    def create_baseline(
        self,
        actor_id: UUID,
        project_id: UUID,
        *,
        baseline_no: str,
        release_version_id: UUID,
        revision_refs: tuple[tuple[UUID, str], ...],
    ) -> Baseline:
        """Create a ``draft`` baseline snapshot of frozen revisions."""
        if not self.authorizer.check(actor_id, project_id, "requirement:baseline"):
            raise PermissionError("FORBIDDEN")
        if not baseline_no.strip():
            raise DomainError("INVALID_BASELINE", "baseline_no is required", 422)
        baseline = Baseline(
            uuid4(), project_id, baseline_no, release_version_id, revision_refs
        )
        self.uow.baselines[(project_id, baseline.id)] = baseline
        self.uow.outbox.append(
            {
                "event_type": "Requirement.BaselineCreated",
                "event_version": 1,
                "project_id": str(project_id),
                "baseline_id": str(baseline.id),
                "baseline_no": baseline.baseline_no,
                "status": baseline.status,
                "version": baseline.version,
            }
        )
        return baseline

    def activate_baseline(
        self, actor_id: UUID, project_id: UUID, baseline_id: UUID
    ) -> Baseline:
        """Activate a non-empty draft baseline exactly once.

        TODO(P1): flipping ``Requirement.baseline_status`` to ``baselined`` for
        every referenced revision is not part of the P0 design (§9.A.5), so a
        baselined requirement is currently only reachable by seeding the store.
        """
        if not self.authorizer.check(actor_id, project_id, "requirement:baseline"):
            raise PermissionError("FORBIDDEN")
        baseline = self.get_baseline(project_id, baseline_id)
        baseline.activate()
        self.uow.baselines[(project_id, baseline.id)] = baseline
        self.uow.outbox.append(
            {
                "event_type": "Requirement.BaselineActivated",
                "event_version": 1,
                "project_id": str(project_id),
                "baseline_id": str(baseline.id),
                "baseline_no": baseline.baseline_no,
                "status": baseline.status,
                "version": baseline.version,
            }
        )
        return baseline

    # ------------------------------------------------------------------
    # Change requests
    # ------------------------------------------------------------------

    def list_change_requests(
        self, project_id: UUID, requirement_id: UUID
    ) -> list[ChangeRequest]:
        """Return every change request opened against one requirement."""
        self._require(project_id, requirement_id)
        values = [
            value
            for (scope, _), value in self.uow.change_requests.items()
            if scope == project_id and value.requirement_id == requirement_id
        ]
        values.sort(key=lambda item: str(item.id))
        return values

    def get_change_request(
        self, project_id: UUID, requirement_id: UUID, change_request_id: UUID
    ) -> ChangeRequest:
        """Load a change request scoped to both project and requirement."""
        value = self.uow.change_requests.get((project_id, change_request_id))
        if value is None or value.requirement_id != requirement_id:
            raise DomainError(
                "RESOURCE_NOT_FOUND", "Change request is not visible", 404
            )
        return value

    def create_change_request(
        self,
        actor_id: UUID,
        project_id: UUID,
        requirement_id: UUID,
        *,
        base_revision_id: UUID,
        proposed_patch: dict[str, Any],
    ) -> ChangeRequest:
        """Open a governed change request against a frozen base revision."""
        if not self.authorizer.check(actor_id, project_id, "requirement:change"):
            raise PermissionError("FORBIDDEN")
        self._require(project_id, requirement_id)
        self._assert_governed_fields(proposed_patch)
        known = {
            revision.id for revision in (self.uow.revisions.get(requirement_id) or [])
        }
        if base_revision_id not in known:
            raise DomainError(
                "RESOURCE_NOT_FOUND",
                "base_revision_id does not belong to this requirement",
                404,
            )
        change = ChangeRequest(
            uuid4(), requirement_id, base_revision_id, dict(proposed_patch)
        )
        self.uow.change_requests[(project_id, change.id)] = change
        self.uow.outbox.append(
            {
                "event_type": "Requirement.ChangeRequested",
                "event_version": 1,
                "project_id": str(project_id),
                "requirement_id": str(requirement_id),
                "change_request_id": str(change.id),
                "base_revision_id": str(base_revision_id),
                "status": change.status,
                "version": change.version,
            }
        )
        return change

    def transition_change_request(
        self,
        actor_id: UUID,
        project_id: UUID,
        requirement_id: UUID,
        change_request_id: UUID,
        *,
        action: str,
    ) -> tuple[ChangeRequest, Requirement]:
        """Advance a change request and apply its patch on ``apply``.

        Applicability is checked *before* the state machine advances so an
        unappliable patch can never leave the change request in ``applied``.
        """
        if not self.authorizer.check(actor_id, project_id, "requirement:change"):
            raise PermissionError("FORBIDDEN")
        requirement = self._require(project_id, requirement_id)
        change = self.get_change_request(project_id, requirement_id, change_request_id)
        if action == "apply":
            self._assert_governed_fields(change.proposed_patch)
        change.transition(action)
        if action == "apply":
            self._apply_fields(project_id, requirement, dict(change.proposed_patch))
            self.uow.requirements[(project_id, requirement.id)] = requirement
        self.uow.change_requests[(project_id, change.id)] = change
        self.uow.outbox.append(
            {
                "event_type": "Requirement.ChangeRequestTransitioned",
                "event_version": 1,
                "project_id": str(project_id),
                "requirement_id": str(requirement_id),
                "change_request_id": str(change.id),
                "action": action,
                "status": change.status,
                "version": change.version,
                "requirement_version": requirement.version,
            }
        )
        return change, requirement

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _require(self, project_id: UUID, requirement_id: UUID) -> Requirement:
        """Load a project-scoped requirement or fail with a 404 domain error."""
        value = self.uow.requirements.get((project_id, requirement_id))
        if value is None:
            raise DomainError("RESOURCE_NOT_FOUND", "Requirement is not visible", 404)
        return value

    def _latest_revision(self, requirement_id: UUID) -> RequirementRevision:
        """Return the highest numbered frozen revision of a requirement."""
        revisions = self.uow.revisions.get(requirement_id) or []
        if not revisions:
            raise DomainError(
                "REVISION_NOT_FOUND", "Requirement has no frozen revision", 409
            )
        return max(revisions, key=lambda item: item.revision_no)

    def _append_revision(self, requirement: Requirement) -> RequirementRevision:
        """Freeze the current content as the next immutable revision."""
        revisions = list(self.uow.revisions.get(requirement.id) or [])
        revision = RequirementRevision.create(
            requirement.id, requirement.current_revision, requirement.snapshot()
        )
        revisions.append(revision)
        self.uow.revisions[requirement.id] = revisions
        return revision

    def _reviews_for(self, requirement_id: UUID) -> list[ReviewRound]:
        """Return the review rounds attached to a requirement's revisions."""
        revision_ids = {
            revision.id for revision in (self.uow.revisions.get(requirement_id) or [])
        }
        values = [
            review
            for review in self.uow.reviews.values()
            if review.revision_id in revision_ids
        ]
        values.sort(key=lambda item: (item.round_no, str(item.id)))
        return values

    def _review_of(self, requirement_id: UUID, review_id: UUID) -> ReviewRound:
        """Load a review round that provably belongs to the requirement."""
        for review in self._reviews_for(requirement_id):
            if review.id == review_id:
                return review
        raise DomainError("RESOURCE_NOT_FOUND", "Review round is not visible", 404)

    def _assert_governed_fields(self, changes: dict[str, Any]) -> None:
        """Reject empty, non-governed and not-yet-persistable patches."""
        if not changes:
            raise DomainError(
                "EMPTY_PATCH", "At least one governed field is required", 422
            )
        unknown = set(changes) - ChangeRequest.ALLOWED_FIELDS
        if unknown:
            raise DomainError(
                "INVALID_CHANGE_PATCH",
                f"Change contains non-governed fields: {', '.join(sorted(unknown))}",
                422,
            )
        unsupported = set(changes) & UNPERSISTED_GOVERNED_FIELDS
        if unsupported:
            raise DomainError(
                "UNSUPPORTED_PATCH_FIELD",
                "Fields are governed but not persisted yet: "
                f"{', '.join(sorted(unsupported))}",
                422,
            )

    def _apply_fields(
        self, project_id: UUID, requirement: Requirement, changes: dict[str, Any]
    ) -> None:
        """Write governed fields, re-run invariants and freeze a new revision."""
        if "title" in changes:
            requirement.title = str(changes["title"])
        if "description" in changes:
            requirement.description = str(changes["description"])
        if "priority" in changes:
            requirement.priority = str(changes["priority"])
        if "owner_id" in changes:
            requirement.owner_id = UUID(str(changes["owner_id"]))
        if "release_version_id" in changes:
            requirement.release_version_id = UUID(str(changes["release_version_id"]))
        if "acceptance_criteria" in changes:
            requirement.acceptance_criteria = list(changes["acceptance_criteria"])
        if "parent_id" in changes:
            self._set_parent(project_id, requirement, changes["parent_id"])
        # Re-run the aggregate invariants: the dataclass validated them once at
        # construction time and a governed update must not be able to bypass them.
        requirement.__post_init__()
        requirement.current_revision += 1
        requirement.version += 1
        self._append_revision(requirement)

    def _set_parent(
        self, project_id: UUID, requirement: Requirement, raw: Any
    ) -> None:
        """Re-parent through the domain so hierarchy and cycles stay guarded."""
        if raw is None or raw == "":
            requirement.set_parent(None)
            return
        parent_id = UUID(str(raw))
        parent = self.uow.requirements.get((project_id, parent_id))
        if parent is None:
            raise DomainError(
                "RESOURCE_NOT_FOUND", "Parent requirement is not visible", 404
            )
        ancestors = self._ancestors(project_id, parent_id) | {parent_id}
        requirement.set_parent(parent, ancestors)

    def _ancestors(self, project_id: UUID, requirement_id: UUID) -> set[UUID]:
        """Walk the parent chain so a re-parent request can never build a cycle."""
        seen: set[UUID] = set()
        current = self.uow.requirements.get((project_id, requirement_id))
        while current is not None and current.parent_id is not None:
            if current.parent_id in seen:
                break
            seen.add(current.parent_id)
            current = self.uow.requirements.get((project_id, current.parent_id))
        return seen

    def portal_summary(
        self,
        project_ids: tuple[str, ...],
        actor_id: str | None = None,
        *,
        cross_project: bool = False,
        review_limit: int = PORTAL_REVIEW_LIMIT_DEFAULT,
    ) -> dict[str, Any]:
        """Build the read-only requirement block of the portal dashboard.

        Args:
            project_ids: Scope pushed down by the gateway; ignored when
                ``cross_project`` is ``True``.
            actor_id: Gateway-verified identity, retained for traceability. The
                frozen contract does not filter reviews per reviewer.
            cross_project: ``True`` only after the caller proved it holds
                ``portal:cross-project-view``.
            review_limit: Maximum number of pending review items returned.

        Returns:
            A mapping with ``total``, ``by_status``, ``baseline_total`` and
            ``pending_reviews``. Every key is always present, even when empty.
        """
        bounded_limit = max(1, min(int(review_limit), PORTAL_REVIEW_LIMIT_MAX))
        requirements = self.uow.portal_requirements(tuple(project_ids), cross_project)
        baseline_total = self.uow.portal_active_baseline_total(tuple(project_ids), cross_project)
        by_status = dict.fromkeys(PORTAL_STATUS_KEYS, 0)
        pending: list[Requirement] = []
        for requirement in requirements:
            by_status[PORTAL_STATUS_MAP[requirement.status]] += 1
            if requirement.status is RequirementStatus.IN_REVIEW:
                pending.append(requirement)
        pending.sort(key=lambda item: (str(item.project_id), item.business_no))
        return {
            "total": len(requirements),
            "by_status": by_status,
            "baseline_total": baseline_total,
            "pending_reviews": {
                "count": len(pending),
                "items": [_portal_review_item(item) for item in pending[:bounded_limit]],
            },
        }


def _portal_review_item(requirement: Requirement) -> dict[str, Any]:
    """Shape one pending review row for the dashboard contract.

    ``updated_at`` is ``None`` because the requirement table intentionally carries
    no timestamp column; adding one would need a schema migration, which the
    portal work explicitly excludes.
    """
    return {
        "id": str(requirement.id),
        "project_id": str(requirement.project_id),
        "business_no": requirement.business_no,
        "title": requirement.title,
        "status": PORTAL_STATUS_MAP[requirement.status],
        "updated_at": None,
    }
