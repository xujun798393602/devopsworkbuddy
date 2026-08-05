"""SQLAlchemy persistence tables for project collaboration."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    """Declarative persistence metadata."""


class ProjectRow(Base):
    __tablename__ = "projects"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    business_no: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    owner_id: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (
        CheckConstraint("status IN ('active','archived')", name="ck_projects_status"),
        Index("ix_projects_owner_id", "owner_id"),
    )


class ProjectMembershipRow(Base):
    __tablename__ = "project_memberships"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    joined_by: Mapped[str] = mapped_column(String(255), nullable=False)
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    removed_by: Mapped[str | None] = mapped_column(String(255))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    __table_args__ = (
        CheckConstraint("role IN ('owner','admin','member','viewer')", name="ck_membership_role"),
        CheckConstraint("status IN ('active','removed')", name="ck_membership_status"),
        Index(
            "uq_membership_active_user",
            "project_id",
            "user_id",
            unique=True,
            postgresql_where=text("status='active'"),
        ),
        Index(
            "uq_membership_active_owner",
            "project_id",
            unique=True,
            postgresql_where=text("status='active' AND role='owner'"),
        ),
        Index("ix_membership_actor", "user_id", "status", "project_id"),
    )


class ProjectCounterRow(Base):
    __tablename__ = "project_counters"
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="RESTRICT"), primary_key=True
    )
    counter_type: Mapped[str] = mapped_column(String(16), primary_key=True)
    next_value: Mapped[int] = mapped_column(Integer, nullable=False)


class ReleaseVersionRow(Base):
    __tablename__ = "release_versions"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    business_no: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    planned_release_date: Mapped[date | None] = mapped_column(Date)
    release_date: Mapped[date | None] = mapped_column(Date)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (
        UniqueConstraint("project_id", "id", name="uq_versions_project_id"),
        UniqueConstraint("project_id", "business_no", name="uq_versions_business_no"),
        CheckConstraint(
            "status IN ('planned','active','released','canceled','archived')",
            name="ck_versions_status",
        ),
        Index(
            "uq_versions_normalized_name", "project_id", func.lower(func.btrim(name)), unique=True
        ),
        Index("ix_versions_project_status", "project_id", "status", "id"),
    )


class IterationRow(Base):
    __tablename__ = "iterations"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    business_no: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    goal: Mapped[str] = mapped_column(Text, nullable=False, default="")
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    capacity_minutes: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (
        UniqueConstraint("project_id", "id", name="uq_iterations_project_id"),
        UniqueConstraint("project_id", "business_no", name="uq_iterations_business_no"),
        CheckConstraint("end_date >= start_date", name="ck_iteration_dates"),
        CheckConstraint(
            "capacity_minutes IS NULL OR capacity_minutes >= 0", name="ck_iteration_capacity"
        ),
        CheckConstraint(
            "status IN ('planned','active','completed','canceled')", name="ck_iterations_status"
        ),
        Index(
            "uq_iterations_normalized_name", "project_id", func.lower(func.btrim(name)), unique=True
        ),
        Index(
            "uq_iterations_active",
            "project_id",
            unique=True,
            postgresql_where=text("status='active'"),
        ),
        Index("ix_iterations_project_status", "project_id", "status", "start_date", "id"),
    )


class TaskRow(Base):
    __tablename__ = "tasks"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    business_no: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    task_type: Mapped[str] = mapped_column(String(32), nullable=False)
    priority: Mapped[str] = mapped_column(String(4), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    creator_id: Mapped[str] = mapped_column(String(255), nullable=False)
    assignee_id: Mapped[str | None] = mapped_column(String(255))
    release_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    iteration_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    planned_start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    planned_end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    actual_start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    actual_end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    estimated_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    workflow_template_key: Mapped[str] = mapped_column(String(64), nullable=False)
    workflow_version: Mapped[int] = mapped_column(Integer, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (
        UniqueConstraint("project_id", "id", name="uq_tasks_project_id"),
        ForeignKeyConstraint(
            ["project_id", "release_version_id"],
            ["release_versions.project_id", "release_versions.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["project_id", "iteration_id"],
            ["iterations.project_id", "iterations.id"],
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "release_version_id IS NOT NULL OR iteration_id IS NOT NULL", name="ck_task_scope"
        ),
        CheckConstraint("estimated_minutes BETWEEN 0 AND 10000000", name="ck_task_estimate"),
        CheckConstraint(
            "planned_end_at IS NULL OR planned_start_at IS NULL OR planned_end_at >= planned_start_at",
            name="ck_task_planned_dates",
        ),
        CheckConstraint(
            "status IN ('todo','in_progress','done','closed','canceled')", name="ck_task_status"
        ),
        Index("ix_tasks_project_status", "project_id", "status", "created_at", "id"),
        Index("ix_tasks_project_assignee", "project_id", "assignee_id", "status", "id"),
    )


class TaskParticipantRow(Base):
    __tablename__ = "task_participants"
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    task_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    added_by: Mapped[str] = mapped_column(String(255), nullable=False)
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "task_id"], ["tasks.project_id", "tasks.id"], ondelete="RESTRICT"
        ),
        Index("ix_participants_project_user", "project_id", "user_id", "task_id"),
    )


class WorklogRow(Base):
    __tablename__ = "worklogs"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    task_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    recorded_by: Mapped[str] = mapped_column(String(255), nullable=False)
    work_date: Mapped[date] = mapped_column(Date, nullable=False)
    minutes_delta: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    corrects_worklog_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("worklogs.id", ondelete="RESTRICT")
    )
    correction_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    __table_args__ = (
        ForeignKeyConstraint(
            ["project_id", "task_id"], ["tasks.project_id", "tasks.id"], ondelete="RESTRICT"
        ),
        CheckConstraint(
            "minutes_delta != 0 AND minutes_delta BETWEEN -1440 AND 1440", name="ck_worklog_delta"
        ),
        Index("ix_worklogs_task", "project_id", "task_id", "work_date", "created_at", "id"),
        Index("ix_worklogs_user_day", "project_id", "user_id", "work_date"),
        Index("ix_worklogs_corrects", "corrects_worklog_id"),
    )


class IdempotencyRecordRow(Base):
    __tablename__ = "idempotency_records"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scope: Mapped[str] = mapped_column(String(300), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    operation: Mapped[str] = mapped_column(
        String(500), nullable=False, default="POST /api/v1/projects"
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    response_status: Mapped[int | None] = mapped_column(Integer)
    resource_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    response_body: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    response_headers: Mapped[dict[str, str] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        UniqueConstraint("scope", "idempotency_key", name="uq_idempotency_scope_key"),
        CheckConstraint("status IN ('processing','completed')", name="ck_idempotency_status"),
        Index("ix_idempotency_expires", "expires_at"),
    )


class AuditRecordRow(Base):
    __tablename__ = "audit_records"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    trace_id: Mapped[str] = mapped_column(String(255), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(255), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    result: Mapped[str] = mapped_column(String(16), nullable=False)
    before: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    after: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(255))
    __table_args__ = (
        Index("ix_audit_project_time", "project_id", "occurred_at", "id"),
        Index("ix_audit_trace", "trace_id"),
        Index("ix_audit_resource", "resource_type", "resource_id", "occurred_at"),
    )


class OutboxEventRow(Base):
    __tablename__ = "outbox_events"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(150), nullable=False)
    event_version: Mapped[int] = mapped_column(Integer, nullable=False)
    aggregate_type: Mapped[str] = mapped_column(String(64), nullable=False)
    aggregate_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    trace_id: Mapped[str] = mapped_column(String(255), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','processing','published','failed')", name="ck_outbox_status"
        ),
        Index("ix_outbox_pending", "status", "available_at", "occurred_at"),
    )
