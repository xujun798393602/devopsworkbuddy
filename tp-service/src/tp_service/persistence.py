"""SQLAlchemy persistence model for TP library and design batch 0001."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Private TP database metadata root."""


class TestFolderRow(Base):
    __tablename__ = "test_folders"
    __table_args__ = (
        UniqueConstraint("project_id", "parent_key", "normalized_name", name="uq_folder_sibling_name"),
        CheckConstraint("version >= 1", name="ck_folder_version"),
        CheckConstraint("depth BETWEEN 0 AND 20", name="ck_folder_depth"),
    )
    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    project_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    parent_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), ForeignKey("test_folders.id"))
    parent_key: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(200), nullable=False)
    path: Mapped[str] = mapped_column(String(4096), nullable=False, default="/")
    depth: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class TestCaseRow(Base):
    __tablename__ = "test_cases"
    __table_args__ = (
        UniqueConstraint("project_id", "business_no", name="uq_case_business_no"),
        Index("ix_case_project_folder_status", "project_id", "folder_id", "status"),
    )
    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    project_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    business_no: Mapped[str] = mapped_column(String(64), nullable=False)
    folder_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("test_folders.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    owner_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    case_type: Mapped[str] = mapped_column(String(32), nullable=False)
    priority: Mapped[str] = mapped_column(String(8), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    automation_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    current_version_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class TestCaseVersionRow(Base):
    __tablename__ = "test_case_versions"
    __table_args__ = (
        UniqueConstraint("case_id", "version_no", name="uq_case_version_no"),
        UniqueConstraint("case_id", "content_hash", name="uq_case_content_hash"),
    )
    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    case_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("test_cases.id"), nullable=False)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    source_design_node_ref: Mapped[str | None] = mapped_column(String(500))
    preconditions: Mapped[str] = mapped_column(Text, nullable=False, default="")
    postconditions: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_by: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class TestCaseStepRow(Base):
    __tablename__ = "test_case_steps"
    __table_args__ = (CheckConstraint("sequence BETWEEN 1 AND 500", name="ck_case_step_sequence"),)
    case_version_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("test_case_versions.id"), primary_key=True
    )
    sequence: Mapped[int] = mapped_column(Integer, primary_key=True)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    expected: Mapped[str] = mapped_column(Text, nullable=False)
    test_data: Mapped[str] = mapped_column(Text, nullable=False, default="")


class DesignSessionRow(Base):
    __tablename__ = "design_sessions"
    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    project_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    created_by: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    target_folder_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("test_folders.id"), nullable=False)
    requirement_snapshot_refs: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    resume_state: Mapped[str | None] = mapped_column(String(32))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class StageRunRow(Base):
    __tablename__ = "stage_runs"
    __table_args__ = (UniqueConstraint("session_id", "stage", "attempt", name="uq_stage_attempt"),)
    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    session_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("design_sessions.id"), nullable=False)
    stage: Mapped[str] = mapped_column(String(16), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    output_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    adapter_key: Mapped[str] = mapped_column(String(64), nullable=False)
    model_version: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)


class ReviewGateRow(Base):
    __tablename__ = "review_gates"
    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    stage_run_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("stage_runs.id"), nullable=False)
    reviewer_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    privileged_exception: Mapped[bool] = mapped_column(nullable=False, default=False)
    comments: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class TestEnvironmentRow(Base):
    __tablename__ = "test_environments"
    __table_args__ = (UniqueConstraint("project_id", "normalized_name", name="uq_environment_name"),)
    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    project_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    normalized_name: Mapped[str] = mapped_column(String(200), nullable=False)
    classification: Mapped[str] = mapped_column(String(16), nullable=False)
    base_url: Mapped[str] = mapped_column(Text, nullable=False)
    configuration_summary: Mapped[str] = mapped_column(String(8192), nullable=False, default="")
    variable_keys: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    secret_ref_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class PlanScopeItemRow(Base):
    """Immutable item in a frozen test-plan scope."""

    __tablename__ = "plan_scope_items"
    plan_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("test_plans.id"), primary_key=True
    )
    sequence: Mapped[int] = mapped_column(Integer, primary_key=True)
    requirement_ref: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    requirement_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    requirement_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    case_version_ref: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    environment_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)


class TestPlanRow(Base):
    __tablename__ = "test_plans"
    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    project_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    business_no: Mapped[str] = mapped_column(String(64), nullable=False)
    owner_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    scope_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class TestExecutionRow(Base):
    __tablename__ = "test_executions"
    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    project_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    plan_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("test_plans.id"), nullable=False)
    environment_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    assignee_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    round_no: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class CaseRunAttemptRow(Base):
    __tablename__ = "case_run_attempts"
    __table_args__ = (UniqueConstraint("execution_id", "case_version_ref", "attempt_no", name="uq_case_run_attempt"),)
    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    execution_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("test_executions.id"), nullable=False)
    case_version_ref: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    actual_result: Mapped[str] = mapped_column(Text, nullable=False, default="")


class TestReportRow(Base):
    __tablename__ = "test_reports"
    __table_args__ = (UniqueConstraint("execution_id", "revision", name="uq_report_revision"),)
    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    project_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    execution_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("test_executions.id"), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    published_by: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    summary: Mapped[dict[str, int]] = mapped_column(JSON, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class TraceabilityLinkRow(Base):
    __tablename__ = "traceability_links"
    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    project_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    source_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    target_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    source_domain: Mapped[str] = mapped_column(String(32), nullable=False)
    source_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    target_domain: Mapped[str] = mapped_column(String(32), nullable=False)
    target_type: Mapped[str] = mapped_column(String(64), nullable=False)
    target_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    link_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    source_event_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, unique=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AutomationAssetRow(Base):
    __tablename__ = "automation_assets"
    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    project_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    normalized_name: Mapped[str] = mapped_column(String(200), nullable=False)
    repository_ref: Mapped[str] = mapped_column(Text, nullable=False)
    case_version_ref: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))


class AutomationSuiteRow(Base):
    __tablename__ = "automation_suites"
    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    project_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    normalized_name: Mapped[str] = mapped_column(String(200), nullable=False)
    asset_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)


class AutomationTaskRow(Base):
    __tablename__ = "automation_tasks"
    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    project_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    suite_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    environment_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    external_run_ref: Mapped[str] = mapped_column(String(500), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)


class ResultIngestionRow(Base):
    __tablename__ = "result_ingestions"
    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    project_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(100), nullable=False)
    external_run_ref: Mapped[str] = mapped_column(String(500), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class AutomationResultItemRow(Base):
    __tablename__ = "automation_result_items"
    ingestion_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("result_ingestions.id"), primary_key=True
    )
    sequence: Mapped[int] = mapped_column(Integer, primary_key=True)
    external_case_ref: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    case_version_ref: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    message: Mapped[str] = mapped_column(String(20000), nullable=False)


class OutboxEventRow(Base):
    """Transactional TP domain event."""

    __tablename__ = "tp_outbox_events"
    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")


class IdempotencyRecordRow(Base):
    """Durable project-scoped idempotency response."""

    __tablename__ = "tp_idempotency_records"
    project_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    actor_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    response_payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    response_status: Mapped[int] = mapped_column(Integer, nullable=False)


class ImportBatchRow(Base):
    __tablename__ = "import_batches"
    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    session_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), ForeignKey("design_sessions.id"), nullable=False)
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    target_folder_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    conflict_strategy: Mapped[str] = mapped_column(String(32), nullable=False)
    validation_summary: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    normalized_ir: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
