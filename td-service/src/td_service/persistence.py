"""SQLAlchemy tables and duplicate-chain recursive CTE guard."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    select,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column


class Base(DeclarativeBase):
    """Declarative metadata root for the TD private database."""


class DefectRow(Base):
    """Mutable defect head; evidence and history are append-only tables."""

    __tablename__ = "defects"
    __table_args__ = (
        UniqueConstraint("project_id", "business_no", name="uq_defect_project_business_no"),
        CheckConstraint("version >= 1", name="ck_defect_version"),
        CheckConstraint("reopen_count >= 0", name="ck_defect_reopen_count"),
        Index("ix_defect_project_status", "project_id", "status", "id"),
        Index("ix_defect_project_assignee", "project_id", "assignee_id", "status"),
        Index("ix_defect_project_severity", "project_id", "severity", "status"),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    project_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    business_no: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    priority: Mapped[str] = mapped_column(String(8), nullable=False)
    defect_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    reporter_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    assignee_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    verifier_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    expected_result: Mapped[str] = mapped_column(Text, nullable=False)
    actual_result: Mapped[str] = mapped_column(Text, nullable=False)
    reproduction_steps: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    affected_version_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    fix_version_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    root_cause: Mapped[str] = mapped_column(Text, nullable=False, default="")
    reopen_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class DefectDuplicateRow(Base):
    """One active duplicate-to-master edge."""

    __tablename__ = "defect_duplicates"
    duplicate_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("defects.id", ondelete="CASCADE"), primary_key=True
    )
    project_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    master_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("defects.id", ondelete="RESTRICT"), nullable=False, index=True
    )


class DefectHistoryRow(Base):
    """Append-only action history."""

    __tablename__ = "defect_history"
    defect_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    sequence_no: Mapped[int] = mapped_column(Integer, primary_key=True)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    before_status: Mapped[str] = mapped_column(String(32), nullable=False)
    after_status: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class DefectSlaRow(Base):
    """Creation-time immutable SLA policy snapshot with mutable observations."""

    __tablename__ = "defect_sla_snapshots"
    defect_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("defects.id", ondelete="CASCADE"), primary_key=True
    )
    policy_key: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(32), nullable=False)
    response_due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolution_due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    first_responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    response_breached: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    resolution_breached: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class FixEvidenceRow(Base):
    """Append-only repair evidence."""

    __tablename__ = "defect_fix_evidence"
    defect_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("defects.id", ondelete="CASCADE"), primary_key=True
    )
    sequence_no: Mapped[int] = mapped_column(Integer, primary_key=True)
    evidence_type: Mapped[str] = mapped_column(String(16), nullable=False)
    external_ref: Mapped[str] = mapped_column(String(500), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)


class VerificationEvidenceRow(Base):
    """Append-only human verification evidence."""

    __tablename__ = "defect_verification_evidence"
    defect_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("defects.id", ondelete="CASCADE"), primary_key=True
    )
    sequence_no: Mapped[int] = mapped_column(Integer, primary_key=True)
    environment_ref: Mapped[str] = mapped_column(String(500), nullable=False)
    conclusion: Mapped[str] = mapped_column(String(16), nullable=False)
    evidence_refs: Mapped[list[str]] = mapped_column(JSON, nullable=False)


class IdempotencyRow(Base):
    """Durable project- and actor-scoped HTTP command result."""

    __tablename__ = "idempotency_records"
    project_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    actor_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    response_payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    response_status: Mapped[int] = mapped_column(Integer, nullable=False)


class OutboxRow(Base):
    """Transactional integration event awaiting publication."""

    __tablename__ = "outbox_events"
    event_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    aggregate_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


def assert_duplicate_edge_is_acyclic(
    session: Session,
    project_id: UUID,
    duplicate_id: UUID,
    master_id: UUID,
) -> None:
    """Reject cross-project, self and recursive duplicate edges before insertion."""
    if duplicate_id == master_id:
        raise ValueError("DUPLICATE_CYCLE")
    master_exists = session.scalar(
        select(DefectRow.id).where(DefectRow.project_id == project_id, DefectRow.id == master_id)
    )
    if master_exists is None:
        raise ValueError("RESOURCE_NOT_FOUND")
    chain = (
        select(DefectDuplicateRow.master_id.label("defect_id"))
        .where(
            DefectDuplicateRow.project_id == project_id,
            DefectDuplicateRow.duplicate_id == master_id,
        )
        .cte("duplicate_chain", recursive=True)
    )
    chain = chain.union_all(
        select(DefectDuplicateRow.master_id).join(chain, DefectDuplicateRow.duplicate_id == chain.c.defect_id).where(
            DefectDuplicateRow.project_id == project_id
        )
    )
    if session.scalar(select(chain.c.defect_id).where(chain.c.defect_id == duplicate_id).limit(1)) is not None:
        raise ValueError("DUPLICATE_CYCLE")
