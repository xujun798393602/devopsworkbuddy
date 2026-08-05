"""SQLAlchemy records for the requirement-service private database."""
from __future__ import annotations

from typing import Any

from sqlalchemy import JSON, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Requirement private metadata root."""


class RequirementRow(Base):
    """Current requirement aggregate state."""

    __tablename__ = "requirements"
    __table_args__ = (UniqueConstraint("project_id", "business_no"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    business_no: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    owner_id: Mapped[str] = mapped_column(String(36), nullable=False)
    release_version_id: Mapped[str] = mapped_column(String(36), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    parent_id: Mapped[str | None] = mapped_column(String(36))
    priority: Mapped[str] = mapped_column(String(8), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    acceptance_criteria: Mapped[list[dict[str, str]]] = mapped_column(JSON, nullable=False)
    current_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    baseline_status: Mapped[str] = mapped_column(String(32), nullable=False)


class RequirementRevisionRow(Base):
    """Immutable full requirement snapshot."""

    __tablename__ = "requirement_revisions"
    __table_args__ = (UniqueConstraint("requirement_id", "revision_no"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    requirement_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    revision_no: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class ReviewRoundRow(Base):
    """Persisted review round with append-only decisions."""

    __tablename__ = "requirement_review_rounds"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    requirement_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    round_no: Mapped[int] = mapped_column(Integer, nullable=False)
    revision_id: Mapped[str] = mapped_column(String(36), nullable=False)
    submitted_by: Mapped[str] = mapped_column(String(36), nullable=False)
    reviewer_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    decisions: Mapped[list[dict[str, str]]] = mapped_column(JSON, nullable=False)


class BaselineRow(Base):
    """Immutable requirement baseline snapshot."""

    __tablename__ = "requirement_baselines"
    __table_args__ = (UniqueConstraint("project_id", "baseline_no"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    baseline_no: Mapped[str] = mapped_column(String(64), nullable=False)
    release_version_id: Mapped[str] = mapped_column(String(36), nullable=False)
    revision_refs: Mapped[list[list[str]]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)


class ChangeRequestRow(Base):
    """Governed change request against an immutable base revision."""

    __tablename__ = "requirement_change_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    requirement_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    base_revision_id: Mapped[str] = mapped_column(String(36), nullable=False)
    proposed_patch: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)


class IdempotencyRow(Base):
    """Durable HTTP command result."""

    __tablename__ = "idempotency_records"

    project_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    actor_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    response_body: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    response_status: Mapped[int] = mapped_column(Integer, nullable=False)


class OutboxRow(Base):
    """Locally transactional domain event."""

    __tablename__ = "outbox_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
