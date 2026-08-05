"""Repository ports and transactional Unit of Work implementations."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, scoped_session, sessionmaker

from td_service.domain import (
    Defect,
    DefectStatus,
    FixEvidence,
    SlaSnapshot,
    VerificationEvidence,
)
from td_service.persistence import (
    DefectDuplicateRow,
    DefectHistoryRow,
    DefectRow,
    DefectSlaRow,
    FixEvidenceRow,
    IdempotencyRow,
    OutboxRow,
    VerificationEvidenceRow,
    assert_duplicate_edge_is_acyclic,
)

IdempotencyValue = tuple[str, dict[str, Any], int]


@dataclass(slots=True)
class MemoryUnitOfWork:
    """Project-scoped adapter used by component tests and local development."""

    defects: dict[tuple[UUID, UUID], Defect] = field(default_factory=dict)
    outbox: list[dict[str, Any]] = field(default_factory=list)
    idempotency: dict[tuple[UUID, UUID, str], IdempotencyValue] = field(default_factory=dict)
    commits: int = 0

    def commit(self) -> None:
        """Record a successful local transaction boundary."""
        self.commits += 1

    def rollback(self) -> None:
        """Leave the explicit in-memory test adapter unchanged."""

    def duplicate_ancestors(self, project_id: UUID, master_id: UUID) -> set[UUID]:
        """Walk the master chain in memory; persistence uses a recursive CTE."""
        ancestors: set[UUID] = set()
        current_id: UUID | None = master_id
        while current_id is not None:
            if current_id in ancestors:
                break
            ancestors.add(current_id)
            current = self.defects.get((project_id, current_id))
            current_id = current.duplicate_of_id if current is not None else None
        return ancestors


class SqlAlchemyUnitOfWork(MemoryUnitOfWork):
    """SQLAlchemy UoW mapping complete defect aggregates to private tables."""

    def __init__(self, session: Session) -> None:
        super().__init__()
        self.session = session
        self._load()

    def _load(self) -> None:
        duplicate_by_id = {
            row.duplicate_id: row.master_id
            for row in self.session.scalars(select(DefectDuplicateRow)).all()
        }
        history_by_id: dict[UUID, list[dict[str, Any]]] = {}
        for row in self.session.scalars(
            select(DefectHistoryRow).order_by(
                DefectHistoryRow.defect_id,
                DefectHistoryRow.sequence_no,
            )
        ):
            history_by_id.setdefault(row.defect_id, []).append(
                {
                    "sequence_no": row.sequence_no,
                    "action": row.action,
                    "actor_id": str(row.actor_id),
                    "from": row.before_status,
                    "to": row.after_status,
                    "reason": row.reason,
                }
            )
        fixes_by_id: dict[UUID, list[FixEvidence]] = {}
        for row in self.session.scalars(
            select(FixEvidenceRow).order_by(
                FixEvidenceRow.defect_id,
                FixEvidenceRow.sequence_no,
            )
        ):
            fixes_by_id.setdefault(row.defect_id, []).append(
                FixEvidence(row.evidence_type, row.external_ref, row.summary)
            )
        verifications_by_id: dict[UUID, list[VerificationEvidence]] = {}
        for row in self.session.scalars(
            select(VerificationEvidenceRow).order_by(
                VerificationEvidenceRow.defect_id,
                VerificationEvidenceRow.sequence_no,
            )
        ):
            verifications_by_id.setdefault(row.defect_id, []).append(
                VerificationEvidence(
                    row.environment_ref,
                    row.conclusion,
                    tuple(row.evidence_refs),
                )
            )
        sla_by_id = {
            row.defect_id: SlaSnapshot(
                policy_key=row.policy_key,
                policy_version=row.policy_version,
                response_due_at=row.response_due_at,
                resolution_due_at=row.resolution_due_at,
                first_responded_at=row.first_responded_at,
                resolved_at=row.resolved_at,
                response_breached=row.response_breached,
                resolution_breached=row.resolution_breached,
            )
            for row in self.session.scalars(select(DefectSlaRow)).all()
        }
        for row in self.session.scalars(select(DefectRow)).all():
            defect = Defect(
                id=row.id,
                project_id=row.project_id,
                business_no=row.business_no,
                title=row.title,
                description=row.description,
                severity=row.severity,
                priority=row.priority,
                defect_type=row.defect_type,
                reporter_id=row.reporter_id,
                expected_result=row.expected_result,
                actual_result=row.actual_result,
                reproduction_steps=tuple(row.reproduction_steps),
                status=DefectStatus(row.status),
                assignee_id=row.assignee_id,
                verifier_id=row.verifier_id,
                affected_version_id=row.affected_version_id,
                fix_version_id=row.fix_version_id,
                root_cause=row.root_cause,
                duplicate_of_id=duplicate_by_id.get(row.id),
                reopen_count=row.reopen_count,
                version=row.version,
                fix_evidence=fixes_by_id.get(row.id, []),
                verification_evidence=verifications_by_id.get(row.id, []),
                history=history_by_id.get(row.id, []),
                sla=sla_by_id.get(row.id),
            )
            self.defects[(defect.project_id, defect.id)] = defect
        for row in self.session.scalars(select(IdempotencyRow)).all():
            self.idempotency[(row.project_id, row.actor_id, row.idempotency_key)] = (
                row.request_hash,
                dict(row.response_payload),
                row.response_status,
            )

    def duplicate_ancestors(self, project_id: UUID, master_id: UUID) -> set[UUID]:
        """Return the persisted duplicate chain including the proposed master."""
        ancestors: set[UUID] = set()
        current_id: UUID | None = master_id
        while current_id is not None and current_id not in ancestors:
            ancestors.add(current_id)
            current_id = self.session.scalar(
                select(DefectDuplicateRow.master_id).where(
                    DefectDuplicateRow.project_id == project_id,
                    DefectDuplicateRow.duplicate_id == current_id,
                )
            )
        return ancestors

    def _save_defect(self, defect: Defect) -> None:
        row = self.session.get(DefectRow, defect.id)
        values = {
            "project_id": defect.project_id,
            "business_no": defect.business_no,
            "title": defect.title,
            "description": defect.description,
            "severity": defect.severity,
            "priority": defect.priority,
            "defect_type": defect.defect_type,
            "status": defect.status.value,
            "reporter_id": defect.reporter_id,
            "assignee_id": defect.assignee_id,
            "verifier_id": defect.verifier_id,
            "expected_result": defect.expected_result,
            "actual_result": defect.actual_result,
            "reproduction_steps": list(defect.reproduction_steps),
            "affected_version_id": defect.affected_version_id,
            "fix_version_id": defect.fix_version_id,
            "root_cause": defect.root_cause,
            "reopen_count": defect.reopen_count,
            "version": defect.version,
        }
        if row is None:
            row = DefectRow(id=defect.id, **values)
            self.session.add(row)
        else:
            for name, value in values.items():
                setattr(row, name, value)
        self.session.flush()
        duplicate_row = self.session.get(DefectDuplicateRow, defect.id)
        if defect.duplicate_of_id is not None and duplicate_row is None:
            assert_duplicate_edge_is_acyclic(
                self.session,
                defect.project_id,
                defect.id,
                defect.duplicate_of_id,
            )
            self.session.add(
                DefectDuplicateRow(
                    duplicate_id=defect.id,
                    project_id=defect.project_id,
                    master_id=defect.duplicate_of_id,
                )
            )
        persisted_history = {
            row.sequence_no: row
            for row in self.session.scalars(
                select(DefectHistoryRow).where(
                    DefectHistoryRow.defect_id == defect.id
                )
            )
        }
        for entry in defect.history:
            sequence_no = int(entry["sequence_no"])
            existing_history = persisted_history.get(sequence_no)
            if existing_history is not None:
                expected = (
                    str(entry["action"]),
                    UUID(str(entry["actor_id"])),
                    str(entry["from"]),
                    str(entry["to"]),
                    str(entry.get("reason", "")),
                )
                actual = (
                    existing_history.action,
                    existing_history.actor_id,
                    existing_history.before_status,
                    existing_history.after_status,
                    existing_history.reason,
                )
                if actual != expected:
                    raise ValueError("DEFECT_HISTORY_APPEND_ONLY")
                continue
            self.session.add(
                DefectHistoryRow(
                    defect_id=defect.id,
                    sequence_no=sequence_no,
                    action=str(entry["action"]),
                    actor_id=UUID(str(entry["actor_id"])),
                    before_status=str(entry["from"]),
                    after_status=str(entry["to"]),
                    reason=str(entry.get("reason", "")),
                    occurred_at=datetime.now(UTC),
                )
            )
        persisted_fixes = {
            row.sequence_no: row
            for row in self.session.scalars(
                select(FixEvidenceRow).where(FixEvidenceRow.defect_id == defect.id)
            )
        }
        for sequence, evidence in enumerate(defect.fix_evidence, start=1):
            existing_fix = persisted_fixes.get(sequence)
            if existing_fix is not None:
                if (
                    existing_fix.evidence_type,
                    existing_fix.external_ref,
                    existing_fix.summary,
                ) != (evidence.type, evidence.external_ref, evidence.summary):
                    raise ValueError("FIX_EVIDENCE_APPEND_ONLY")
                continue
            self.session.add(
                FixEvidenceRow(
                    defect_id=defect.id,
                    sequence_no=sequence,
                    evidence_type=evidence.type,
                    external_ref=evidence.external_ref,
                    summary=evidence.summary,
                )
            )
        persisted_verifications = {
            row.sequence_no: row
            for row in self.session.scalars(
                select(VerificationEvidenceRow).where(
                    VerificationEvidenceRow.defect_id == defect.id
                )
            )
        }
        for sequence, evidence in enumerate(defect.verification_evidence, start=1):
            existing_verification = persisted_verifications.get(sequence)
            if existing_verification is not None:
                if (
                    existing_verification.environment_ref,
                    existing_verification.conclusion,
                    tuple(existing_verification.evidence_refs),
                ) != (
                    evidence.environment_ref,
                    evidence.conclusion,
                    evidence.evidence_refs,
                ):
                    raise ValueError("VERIFICATION_EVIDENCE_APPEND_ONLY")
                continue
            self.session.add(
                VerificationEvidenceRow(
                    defect_id=defect.id,
                    sequence_no=sequence,
                    environment_ref=evidence.environment_ref,
                    conclusion=evidence.conclusion,
                    evidence_refs=list(evidence.evidence_refs),
                )
            )
        if defect.sla is not None:
            sla_row = self.session.get(DefectSlaRow, defect.id)
            if sla_row is None:
                self.session.add(
                    DefectSlaRow(
                        defect_id=defect.id,
                        policy_key=defect.sla.policy_key,
                        policy_version=defect.sla.policy_version,
                        response_due_at=defect.sla.response_due_at,
                        resolution_due_at=defect.sla.resolution_due_at,
                        first_responded_at=defect.sla.first_responded_at,
                        resolved_at=defect.sla.resolved_at,
                        response_breached=defect.sla.response_breached,
                        resolution_breached=defect.sla.resolution_breached,
                    )
                )
            else:
                immutable_policy = (
                    sla_row.policy_key,
                    sla_row.policy_version,
                    sla_row.response_due_at,
                    sla_row.resolution_due_at,
                )
                candidate_policy = (
                    defect.sla.policy_key,
                    defect.sla.policy_version,
                    defect.sla.response_due_at,
                    defect.sla.resolution_due_at,
                )
                if immutable_policy != candidate_policy:
                    raise ValueError("SLA_POLICY_SNAPSHOT_IMMUTABLE")
                sla_row.first_responded_at = defect.sla.first_responded_at
                sla_row.resolved_at = defect.sla.resolved_at
                sla_row.response_breached = defect.sla.response_breached
                sla_row.resolution_breached = defect.sla.resolution_breached

    def commit(self) -> None:
        """Persist aggregates, idempotency results and Outbox in one transaction."""
        try:
            for defect in self.defects.values():
                self._save_defect(defect)
            for (project_id, actor_id, key), value in self.idempotency.items():
                row = self.session.get(IdempotencyRow, (project_id, actor_id, key))
                if row is None:
                    self.session.add(
                        IdempotencyRow(
                            project_id=project_id,
                            actor_id=actor_id,
                            idempotency_key=key,
                            request_hash=value[0],
                            response_payload=value[1],
                            response_status=value[2],
                        )
                    )
            for event in self.outbox:
                self.session.add(
                    OutboxRow(
                        event_id=uuid4(),
                        aggregate_id=UUID(str(event["defect_id"])),
                        event_type=str(event["event_type"]),
                        payload=dict(event),
                        occurred_at=datetime.now(UTC),
                    )
                )
            self.session.commit()
            self.outbox.clear()
            self.commits += 1
        except Exception:
            self.session.rollback()
            raise

    def rollback(self) -> None:
        """Rollback the active SQL transaction."""
        self.session.rollback()


class SqlAlchemyRuntime:
    """Own the engine and request-scoped SQLAlchemy sessions."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.sessions = scoped_session(sessionmaker(engine, expire_on_commit=False))

    def unit_of_work(self) -> SqlAlchemyUnitOfWork:
        """Create a UoW bound to the current request session."""
        return SqlAlchemyUnitOfWork(self.sessions)

    def ready(self) -> None:
        """Raise when the private database cannot answer a trivial query."""
        with self.engine.connect() as connection:
            connection.execute(text("SELECT 1"))

    def remove(self) -> None:
        """Release the request-scoped session."""
        self.sessions.remove()


class AllowAllAuthorizer:
    """Explicit local adapter; production authorization is fail-closed."""

    def check(self, actor_id: UUID, project_id: UUID, action: str) -> bool:
        """Allow identities with a non-empty scoped permission request."""
        return bool(actor_id and project_id and action)
