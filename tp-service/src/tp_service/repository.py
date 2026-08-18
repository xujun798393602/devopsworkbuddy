"""TP repository ports and SQLAlchemy unit of work."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import and_, func, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, scoped_session, sessionmaker

from tp_service.domain import (
    CaseRun,
    DesignSession,
    DomainError,
    ReviewGate,
    SessionStatus,
    StageRun,
    TestCase,
    TestCaseVersion,
    TestExecution,
    TestFolder,
    TestReport,
    TestStep,
)
from tp_service.execution import (
    AutomationAsset,
    AutomationIngestion,
    AutomationResultItem,
    AutomationSuite,
    AutomationTask,
    ManagedEnvironment,
    ManagedExecution,
    ManagedPlan,
    PlanScopeSnapshot,
    PublishedReport,
)
from tp_service.persistence import (
    AutomationAssetRow,
    AutomationResultItemRow,
    AutomationSuiteRow,
    AutomationTaskRow,
    CaseRunAttemptRow,
    DesignSessionRow,
    IdempotencyRecordRow,
    ImportBatchRow,
    OutboxEventRow,
    PlanScopeItemRow,
    ResultIngestionRow,
    ReviewGateRow,
    StageRunRow,
    TestCaseRow,
    TestCaseStepRow,
    TestCaseVersionRow,
    TestEnvironmentRow,
    TestExecutionRow,
    TestFolderRow,
    TestPlanRow,
    TestReportRow,
    TraceabilityLinkRow,
)
from tp_service.traceability import TraceabilityLink, TraceEndpoint

IdempotencyValue = tuple[str, dict[str, Any], int]
ROOT_PARENT_KEY = UUID("ffffffff-ffff-ffff-ffff-ffffffffffff")
SYSTEM_ACTOR_ID = UUID("eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee")


@dataclass(frozen=True, slots=True)
class PortalExecutionSnapshot:
    """Read-only execution projection consumed by the portal dashboard aggregation.

    ``latest_attempt_counts`` maps a case-run status to the number of *latest*
    attempts holding that status inside the execution. Only the latest attempt of
    each ``case_version_ref`` is counted so that reruns never inflate the totals.
    """

    id: UUID
    project_id: UUID
    plan_id: UUID
    assignee_id: UUID
    round_no: int
    status: str
    plan_business_no: str
    latest_attempt_counts: dict[str, int] = field(default_factory=dict)


def _portal_scope(project_ids: tuple[UUID, ...] | list[UUID]) -> tuple[UUID, ...]:
    """Deduplicate the requested project identifiers while preserving order."""
    return tuple(dict.fromkeys(project_ids))


@dataclass(slots=True)
class MemoryPortalRepository:
    """Portal projections computed from the explicit in-memory adapter."""

    uow: MemoryUnitOfWork

    @staticmethod
    def _visible(project_id: UUID, scope: set[UUID] | None) -> bool:
        """Return whether a project falls inside the effective portal scope."""
        return scope is None or project_id in scope

    @staticmethod
    def _scope(
        project_ids: tuple[UUID, ...] | list[UUID],
        cross_project: bool,
    ) -> set[UUID] | None:
        """Return ``None`` for a platform-wide scope or the explicit project set."""
        if cross_project:
            return None
        return set(project_ids)

    def case_total(
        self,
        project_ids: tuple[UUID, ...] | list[UUID],
        cross_project: bool = False,
    ) -> int:
        """Count test cases inside the effective scope."""
        scope = self._scope(project_ids, cross_project)
        return sum(1 for (project_id, _) in self.uow.cases if self._visible(project_id, scope))

    def plan_total(
        self,
        project_ids: tuple[UUID, ...] | list[UUID],
        cross_project: bool = False,
    ) -> int:
        """Count test plans inside the effective scope."""
        scope = self._scope(project_ids, cross_project)
        return sum(1 for (project_id, _) in self.uow.plans if self._visible(project_id, scope))

    def executions(
        self,
        project_ids: tuple[UUID, ...] | list[UUID],
        cross_project: bool = False,
    ) -> list[PortalExecutionSnapshot]:
        """Return deterministic execution snapshots inside the effective scope."""
        scope = self._scope(project_ids, cross_project)
        snapshots: list[PortalExecutionSnapshot] = []
        for (project_id, _), managed in self.uow.executions.items():
            if not self._visible(project_id, scope):
                continue
            aggregate = managed.aggregate
            counts: dict[str, int] = {}
            for attempts in aggregate.attempts.values():
                if not attempts:
                    continue
                latest = max(attempts, key=lambda attempt: attempt.attempt_no)
                counts[latest.status] = counts.get(latest.status, 0) + 1
            plan = self.uow.plans.get((aggregate.project_id, aggregate.plan_id))
            snapshots.append(
                PortalExecutionSnapshot(
                    aggregate.id,
                    aggregate.project_id,
                    aggregate.plan_id,
                    aggregate.assignee_id,
                    managed.round_no,
                    aggregate.status,
                    plan.business_no if plan is not None else "",
                    counts,
                )
            )
        snapshots.sort(
            key=lambda item: (
                str(item.project_id),
                item.plan_business_no,
                item.round_no,
                str(item.id),
            )
        )
        return snapshots


class SqlAlchemyPortalRepository:
    """Batched read-only SQL projections for the portal dashboard.

    Every method issues at most one statement covering the whole project set so
    that a dashboard fan-out never degenerates into an N+1 query pattern.
    """

    def __init__(self, session: Session) -> None:
        self.session = session

    @staticmethod
    def _empty(project_ids: tuple[UUID, ...] | list[UUID], cross_project: bool) -> bool:
        """Return whether the effective scope can only produce zero values."""
        return not cross_project and not project_ids

    def case_total(
        self,
        project_ids: tuple[UUID, ...] | list[UUID],
        cross_project: bool = False,
    ) -> int:
        """Count test cases with one aggregate statement."""
        if self._empty(project_ids, cross_project):
            return 0
        statement = select(func.count()).select_from(TestCaseRow)
        if not cross_project:
            statement = statement.where(TestCaseRow.project_id.in_(tuple(project_ids)))
        return int(self.session.scalar(statement) or 0)

    def plan_total(
        self,
        project_ids: tuple[UUID, ...] | list[UUID],
        cross_project: bool = False,
    ) -> int:
        """Count test plans with one aggregate statement."""
        if self._empty(project_ids, cross_project):
            return 0
        statement = select(func.count()).select_from(TestPlanRow)
        if not cross_project:
            statement = statement.where(TestPlanRow.project_id.in_(tuple(project_ids)))
        return int(self.session.scalar(statement) or 0)

    def _latest_attempt_counts(
        self,
        project_ids: tuple[UUID, ...] | list[UUID],
        cross_project: bool,
    ) -> dict[UUID, dict[str, int]]:
        """Group latest case-run attempt statuses per execution in one statement."""
        latest = (
            select(
                CaseRunAttemptRow.execution_id.label("execution_id"),
                CaseRunAttemptRow.case_version_ref.label("case_version_ref"),
                func.max(CaseRunAttemptRow.attempt_no).label("attempt_no"),
            )
            .group_by(CaseRunAttemptRow.execution_id, CaseRunAttemptRow.case_version_ref)
            .subquery()
        )
        statement = (
            select(
                CaseRunAttemptRow.execution_id,
                CaseRunAttemptRow.status,
                func.count().label("total"),
            )
            .join(
                latest,
                and_(
                    CaseRunAttemptRow.execution_id == latest.c.execution_id,
                    CaseRunAttemptRow.case_version_ref == latest.c.case_version_ref,
                    CaseRunAttemptRow.attempt_no == latest.c.attempt_no,
                ),
            )
            .join(TestExecutionRow, TestExecutionRow.id == CaseRunAttemptRow.execution_id)
            .group_by(CaseRunAttemptRow.execution_id, CaseRunAttemptRow.status)
        )
        if not cross_project:
            statement = statement.where(TestExecutionRow.project_id.in_(tuple(project_ids)))
        counts: dict[UUID, dict[str, int]] = {}
        for execution_id, status, total in self.session.execute(statement):
            counts.setdefault(execution_id, {})[str(status)] = int(total)
        return counts

    def executions(
        self,
        project_ids: tuple[UUID, ...] | list[UUID],
        cross_project: bool = False,
    ) -> list[PortalExecutionSnapshot]:
        """Return execution snapshots joined with their plan business number."""
        if self._empty(project_ids, cross_project):
            return []
        counts = self._latest_attempt_counts(project_ids, cross_project)
        statement = (
            select(TestExecutionRow, TestPlanRow.business_no)
            .join(TestPlanRow, TestPlanRow.id == TestExecutionRow.plan_id, isouter=True)
            .order_by(
                TestExecutionRow.project_id,
                TestExecutionRow.plan_id,
                TestExecutionRow.round_no,
                TestExecutionRow.id,
            )
        )
        if not cross_project:
            statement = statement.where(TestExecutionRow.project_id.in_(tuple(project_ids)))
        snapshots: list[PortalExecutionSnapshot] = []
        for row, business_no in self.session.execute(statement):
            snapshots.append(
                PortalExecutionSnapshot(
                    row.id,
                    row.project_id,
                    row.plan_id,
                    row.assignee_id,
                    row.round_no,
                    row.status,
                    business_no or "",
                    dict(counts.get(row.id, {})),
                )
            )
        return snapshots


@dataclass(slots=True)
class MemoryUnitOfWork:
    """Project-scoped in-memory adapter for explicit tests and local development."""

    folders: dict[tuple[UUID, UUID], TestFolder] = field(default_factory=dict)
    cases: dict[tuple[UUID, UUID], TestCase] = field(default_factory=dict)
    case_versions: dict[UUID, list[TestCaseVersion]] = field(default_factory=dict)
    sessions: dict[tuple[UUID, UUID], DesignSession] = field(default_factory=dict)
    import_batches: list[dict[str, Any]] = field(default_factory=list)
    environments: dict[tuple[UUID, UUID], ManagedEnvironment] = field(default_factory=dict)
    plans: dict[tuple[UUID, UUID], ManagedPlan] = field(default_factory=dict)
    executions: dict[tuple[UUID, UUID], ManagedExecution] = field(default_factory=dict)
    reports: dict[tuple[UUID, UUID], list[PublishedReport]] = field(default_factory=dict)
    automation_assets: dict[tuple[UUID, UUID], AutomationAsset] = field(default_factory=dict)
    automation_suites: dict[tuple[UUID, UUID], AutomationSuite] = field(default_factory=dict)
    automation_tasks: dict[tuple[UUID, UUID], AutomationTask] = field(default_factory=dict)
    ingestions: dict[tuple[UUID, str, str], AutomationIngestion] = field(default_factory=dict)
    traceability_links: dict[UUID, TraceabilityLink] = field(default_factory=dict)
    outbox: list[dict[str, Any]] = field(default_factory=list)
    idempotency: dict[tuple[UUID, UUID, str], IdempotencyValue] = field(default_factory=dict)
    commits: int = 0

    def commit(self) -> None:
        """Record a successful in-memory transaction boundary."""
        self.commits += 1

    def rollback(self) -> None:
        """Rollback is intentionally a no-op for the explicit memory adapter."""

    def folder_descendants(self, project_id: UUID, folder_id: UUID) -> set[UUID]:
        """Return descendants using the authoritative parent relation."""
        descendants: set[UUID] = set()
        frontier = {folder_id}
        for _ in range(20):
            children = {
                item.id
                for (scope, _), item in self.folders.items()
                if scope == project_id and item.parent_id in frontier
            } - descendants
            if not children:
                return descendants
            descendants.update(children)
            frontier = children
        if any(
            scope == project_id and item.parent_id in frontier
            for (scope, _), item in self.folders.items()
        ):
            raise ValueError("FOLDER_DEPTH_EXCEEDED")
        return descendants

    def normalized_folder_name_exists(
        self,
        project_id: UUID,
        parent_id: UUID | None,
        name: str,
        excluding: UUID | None = None,
    ) -> bool:
        """Enforce sibling uniqueness including a null parent."""
        normalized = " ".join(name.casefold().split())
        return any(
            scope == project_id
            and item.id != excluding
            and item.parent_id == parent_id
            and " ".join(item.name.casefold().split()) == normalized
            for (scope, _), item in self.folders.items()
        )


class SqlAlchemyUnitOfWork(MemoryUnitOfWork):
    """Map TP aggregates to normalized SQL rows in one transaction."""

    def __init__(self, session: Session) -> None:
        super().__init__()
        self.session = session
        self._load()

    def _load(self) -> None:
        self._load_folders()
        self._load_cases()
        self._load_sessions()
        self._load_imports()
        self._load_execution_domain()
        self._load_automation()
        self._load_traceability()
        for row in self.session.scalars(select(IdempotencyRecordRow)).all():
            self.idempotency[(row.project_id, row.actor_id, row.idempotency_key)] = (
                row.request_hash,
                dict(row.response_payload),
                row.response_status,
            )

    def _load_folders(self) -> None:
        for row in self.session.scalars(select(TestFolderRow)).all():
            folder = TestFolder(row.id, row.project_id, row.name, row.parent_id, row.version)
            self.folders[(row.project_id, row.id)] = folder

    def _load_cases(self) -> None:
        steps_by_version: dict[UUID, list[TestStep]] = {}
        for row in self.session.scalars(
            select(TestCaseStepRow).order_by(TestCaseStepRow.case_version_id, TestCaseStepRow.sequence)
        ).all():
            steps_by_version.setdefault(row.case_version_id, []).append(
                TestStep(row.sequence, row.action, row.expected, row.test_data)
            )
        for row in self.session.scalars(
            select(TestCaseVersionRow).order_by(TestCaseVersionRow.case_id, TestCaseVersionRow.version_no)
        ).all():
            version = TestCaseVersion(
                row.id,
                row.case_id,
                row.version_no,
                row.content_hash,
                tuple(steps_by_version.get(row.id, [])),
                row.source,
            )
            self.case_versions.setdefault(row.case_id, []).append(version)
        for row in self.session.scalars(select(TestCaseRow)).all():
            case = TestCase(
                row.id,
                row.project_id,
                row.business_no,
                row.folder_id,
                row.title,
                row.owner_id,
                row.case_type,
                row.priority,
                row.status,
                row.automation_mode,
                row.current_version_id,
                (),
                row.version,
            )
            self.cases[(row.project_id, row.id)] = case

    def _load_sessions(self) -> None:
        runs: dict[UUID, list[StageRun]] = {}
        run_sessions: dict[UUID, UUID] = {}
        for row in self.session.scalars(
            select(StageRunRow).order_by(StageRunRow.session_id, StageRunRow.stage, StageRunRow.attempt)
        ).all():
            runs.setdefault(row.session_id, []).append(
                StageRun(
                    row.id,
                    row.stage,
                    row.attempt,
                    row.input_hash,
                    row.status,
                    row.provider,
                    row.output_hash,
                    row.adapter_key,
                    row.model_version,
                    row.prompt_version,
                )
            )
            run_sessions[row.id] = row.session_id
        approved: dict[UUID, set[str]] = {}
        gates: dict[UUID, list[ReviewGate]] = {}
        run_stage = {run.id: run.stage for values in runs.values() for run in values}
        for gate in self.session.scalars(
            select(ReviewGateRow).order_by(ReviewGateRow.created_at, ReviewGateRow.id)
        ).all():
            session_id = run_sessions.get(gate.stage_run_id)
            if session_id is None:
                continue
            gates.setdefault(session_id, []).append(
                ReviewGate(
                    gate.id,
                    gate.stage_run_id,
                    gate.reviewer_id,
                    gate.decision,
                    gate.privileged_exception,
                    gate.comments,
                    gate.created_at,
                )
            )
            if gate.decision == "approved":
                approved.setdefault(session_id, set()).add(run_stage[gate.stage_run_id])
        for row in self.session.scalars(select(DesignSessionRow)).all():
            aggregate = DesignSession(
                row.id,
                row.project_id,
                row.created_by,
                tuple(row.requirement_snapshot_refs),
                row.target_folder_id,
                SessionStatus(row.status),
                row.version,
                runs.get(row.id, []),
                approved.get(row.id, set()),
                gates.get(row.id, []),
            )
            self.sessions[(row.project_id, row.id)] = aggregate

    def _load_imports(self) -> None:
        for row in self.session.scalars(select(ImportBatchRow)).all():
            self.import_batches.append(
                {
                    "id": str(row.id),
                    "session_id": str(row.session_id),
                    "source_hash": row.source_hash,
                    "target_folder_id": str(row.target_folder_id),
                    "conflict_strategy": row.conflict_strategy,
                    "validation_summary": dict(row.validation_summary),
                    "status": row.status,
                }
            )

    def _load_execution_domain(self) -> None:
        for row in self.session.scalars(select(TestEnvironmentRow)).all():
            value = ManagedEnvironment(
                row.id,
                row.project_id,
                row.normalized_name,
                row.classification,
                row.base_url,
                row.configuration_summary,
                tuple(row.variable_keys),
                row.secret_ref_count,
            )
            self.environments[(row.project_id, row.id)] = value
        scopes: dict[UUID, list[PlanScopeSnapshot]] = {}
        for row in self.session.scalars(
            select(PlanScopeItemRow).order_by(PlanScopeItemRow.plan_id, PlanScopeItemRow.sequence)
        ).all():
            scopes.setdefault(row.plan_id, []).append(
                PlanScopeSnapshot(
                    row.requirement_ref,
                    row.requirement_revision,
                    row.requirement_hash,
                    row.case_version_ref,
                    row.environment_id,
                )
            )
        for row in self.session.scalars(select(TestPlanRow)).all():
            value = ManagedPlan(
                row.id,
                row.project_id,
                row.business_no,
                row.owner_id,
                row.status,
                tuple(scopes.get(row.id, [])),
                row.scope_hash,
                row.version,
            )
            self.plans[(row.project_id, row.id)] = value
        attempts: dict[UUID, dict[UUID, list[CaseRun]]] = {}
        for row in self.session.scalars(
            select(CaseRunAttemptRow).order_by(
                CaseRunAttemptRow.execution_id,
                CaseRunAttemptRow.case_version_ref,
                CaseRunAttemptRow.attempt_no,
            )
        ).all():
            attempts.setdefault(row.execution_id, {}).setdefault(row.case_version_ref, []).append(
                CaseRun(row.id, row.case_version_ref, row.attempt_no, row.status, row.actual_result)
            )
        for row in self.session.scalars(select(TestExecutionRow)).all():
            aggregate = TestExecution(
                row.id,
                row.project_id,
                row.plan_id,
                row.environment_id,
                row.assignee_id,
                row.status,
                attempts.get(row.id, {}),
                row.version,
            )
            self.executions[(row.project_id, row.id)] = ManagedExecution(aggregate, row.round_no)
        for row in self.session.scalars(
            select(TestReportRow).order_by(TestReportRow.execution_id, TestReportRow.revision)
        ).all():
            report = TestReport(row.id, row.execution_id, row.published_by, dict(row.summary), row.content_hash)
            self.reports.setdefault((row.project_id, row.execution_id), []).append(
                PublishedReport(report, row.project_id, row.revision)
            )

    def _load_automation(self) -> None:
        for row in self.session.scalars(select(AutomationAssetRow)).all():
            value = AutomationAsset(row.id, row.project_id, row.normalized_name, row.repository_ref, row.case_version_ref)
            self.automation_assets[(row.project_id, row.id)] = value
        for row in self.session.scalars(select(AutomationSuiteRow)).all():
            value = AutomationSuite(row.id, row.project_id, row.normalized_name, tuple(UUID(item) for item in row.asset_ids))
            self.automation_suites[(row.project_id, row.id)] = value
        for row in self.session.scalars(select(AutomationTaskRow)).all():
            value = AutomationTask(row.id, row.project_id, row.suite_id, row.environment_id, row.status, row.external_run_ref, row.version)
            self.automation_tasks[(row.project_id, row.id)] = value
        items: dict[UUID, list[AutomationResultItem]] = {}
        for row in self.session.scalars(
            select(AutomationResultItemRow).order_by(
                AutomationResultItemRow.ingestion_id, AutomationResultItemRow.sequence
            )
        ).all():
            items.setdefault(row.ingestion_id, []).append(
                AutomationResultItem(
                    row.external_case_ref,
                    row.status,
                    row.case_version_ref,
                    row.duration_ms,
                    row.message,
                )
            )
        for row in self.session.scalars(select(ResultIngestionRow)).all():
            value = AutomationIngestion(
                row.id,
                row.project_id,
                row.source,
                row.external_run_ref,
                row.payload_hash,
                tuple(items.get(row.id, [])),
            )
            self.ingestions[(row.project_id, row.source, row.external_run_ref)] = value

    def _load_traceability(self) -> None:
        for row in self.session.scalars(select(TraceabilityLinkRow)).all():
            source = TraceEndpoint(row.project_id, row.source_domain, row.source_type, row.source_id, row.source_revision)
            target = TraceEndpoint(row.project_id, row.target_domain, row.target_type, row.target_id, row.target_revision)
            self.traceability_links[row.id] = TraceabilityLink(
                row.id, source, target, row.link_type, row.source_event_id, row.occurred_at, row.status
            )

    @staticmethod
    def _put(session: Session, row_type: type[Any], identity: Any, values: dict[str, Any]) -> None:
        row = session.get(row_type, identity)
        if row is None:
            session.add(row_type(**values))
            return
        for key, value in values.items():
            setattr(row, key, value)

    def _save_library(self) -> None:
        root_key = ROOT_PARENT_KEY
        for folder in self.folders.values():
            parent = self.folders.get((folder.project_id, folder.parent_id)) if folder.parent_id else None
            depth = 0
            path_parts = [str(folder.id)]
            while parent is not None:
                depth += 1
                path_parts.append(str(parent.id))
                parent = self.folders.get((folder.project_id, parent.parent_id)) if parent.parent_id else None
            self._put(self.session, TestFolderRow, folder.id, {
                "id": folder.id, "project_id": folder.project_id, "parent_id": folder.parent_id,
                "parent_key": folder.parent_id or root_key, "name": folder.name,
                "normalized_name": " ".join(folder.name.casefold().split()),
                "path": "/" + "/".join(reversed(path_parts)), "depth": depth,
                "status": "active", "version": folder.version,
            })
        for case in self.cases.values():
            self._put(self.session, TestCaseRow, case.id, {
                "id": case.id, "project_id": case.project_id, "business_no": case.business_no,
                "folder_id": case.folder_id, "title": case.title, "owner_id": case.owner_id,
                "case_type": case.type, "priority": case.priority, "status": case.status,
                "automation_mode": case.automation_mode, "current_version_id": case.current_version_id,
                "version": case.version,
            })
        for versions in self.case_versions.values():
            for version in versions:
                if self.session.get(TestCaseVersionRow, version.id) is None:
                    self.session.add(TestCaseVersionRow(
                        id=version.id, case_id=version.case_id, version_no=version.version_no,
                        content_hash=version.content_hash, source=version.source,
                        source_design_node_ref=None, preconditions="", postconditions="",
                        created_by=SYSTEM_ACTOR_ID, created_at=datetime.now(UTC),
                    ))
                for step in version.steps:
                    identity = (version.id, step.sequence)
                    if self.session.get(TestCaseStepRow, identity) is None:
                        self.session.add(TestCaseStepRow(
                            case_version_id=version.id, sequence=step.sequence, action=step.action,
                            expected=step.expected, test_data=step.test_data,
                        ))

    def _save_sessions(self) -> None:
        existing_gate_ids = set(self.session.scalars(select(ReviewGateRow.id)).all())
        for aggregate in self.sessions.values():
            self._put(self.session, DesignSessionRow, aggregate.id, {
                "id": aggregate.id, "project_id": aggregate.project_id,
                "created_by": aggregate.created_by, "target_folder_id": aggregate.target_folder_id,
                "requirement_snapshot_refs": list(aggregate.requirement_snapshot_refs),
                "status": aggregate.status.value, "resume_state": None, "version": aggregate.version,
            })
            for run in aggregate.runs:
                self._put(self.session, StageRunRow, run.id, {
                    "id": run.id, "session_id": aggregate.id, "stage": run.stage,
                    "attempt": run.attempt, "input_hash": run.input_hash,
                    "output_hash": run.output_hash, "status": run.status, "provider": run.provider,
                    "adapter_key": run.adapter_key, "model_version": run.model_version,
                    "prompt_version": run.prompt_version,
                })
            for gate in aggregate.review_gates:
                if gate.id in existing_gate_ids:
                    continue
                self.session.add(ReviewGateRow(
                    id=gate.id,
                    stage_run_id=gate.stage_run_id,
                    reviewer_id=gate.reviewer_id,
                    decision=gate.decision,
                    privileged_exception=gate.privileged_exception,
                    comments=gate.comments,
                    created_at=gate.created_at,
                ))
        for batch in self.import_batches:
            batch_id = UUID(str(batch["id"]))
            if self.session.get(ImportBatchRow, batch_id) is None:
                self.session.add(ImportBatchRow(
                    id=batch_id, session_id=UUID(str(batch["session_id"])),
                    source_hash=str(batch["source_hash"]),
                    target_folder_id=UUID(str(batch["target_folder_id"])),
                    conflict_strategy=str(batch["conflict_strategy"]),
                    validation_summary=dict(batch["validation_summary"]), normalized_ir=b"",
                    status=str(batch["status"]),
                ))

    def _save_execution_domain(self) -> None:
        for value in self.environments.values():
            self._put(self.session, TestEnvironmentRow, value.id, {
                "id": value.id, "project_id": value.project_id,
                "normalized_name": " ".join(value.name.split()), "classification": value.classification,
                "base_url": value.base_url, "configuration_summary": value.configuration_summary,
                "variable_keys": list(value.variable_keys), "secret_ref_count": value.secret_ref_count,
            })
        for plan in self.plans.values():
            self._put(self.session, TestPlanRow, plan.id, {
                "id": plan.id, "project_id": plan.project_id, "business_no": plan.business_no,
                "owner_id": plan.owner_id, "status": plan.status, "scope_hash": plan.scope_hash,
                "version": plan.version,
            })
            persisted_scope = self.session.scalars(
                select(PlanScopeItemRow)
                .where(PlanScopeItemRow.plan_id == plan.id)
                .order_by(PlanScopeItemRow.sequence)
            ).all()
            expected_scope = [
                (
                    item.requirement_ref,
                    item.requirement_revision,
                    item.requirement_hash,
                    item.case_version_ref,
                    item.environment_id,
                )
                for item in plan.scope
            ]
            actual_scope = [
                (
                    item.requirement_ref,
                    item.requirement_revision,
                    item.requirement_hash,
                    item.case_version_ref,
                    item.environment_id,
                )
                for item in persisted_scope
            ]
            if persisted_scope and actual_scope != expected_scope:
                raise DomainError("PLAN_SCOPE_FROZEN", "Persisted plan scope is immutable")
            if not persisted_scope:
                self.session.add_all([
                    PlanScopeItemRow(
                        plan_id=plan.id, sequence=index, requirement_ref=item.requirement_ref,
                        requirement_revision=item.requirement_revision, requirement_hash=item.requirement_hash,
                        case_version_ref=item.case_version_ref, environment_id=item.environment_id,
                    )
                    for index, item in enumerate(plan.scope, start=1)
                ])
        for value in self.executions.values():
            aggregate = value.aggregate
            self._put(self.session, TestExecutionRow, aggregate.id, {
                "id": aggregate.id, "project_id": aggregate.project_id, "plan_id": aggregate.plan_id,
                "environment_id": aggregate.environment_id, "assignee_id": aggregate.assignee_id,
                "round_no": value.round_no, "status": aggregate.status, "version": aggregate.version,
            })
            for attempts in aggregate.attempts.values():
                for attempt in attempts:
                    persisted = self.session.get(CaseRunAttemptRow, attempt.id)
                    if persisted is None:
                        self.session.add(CaseRunAttemptRow(
                            id=attempt.id,
                            execution_id=aggregate.id,
                            case_version_ref=attempt.case_version_ref,
                            attempt_no=attempt.attempt_no,
                            status=attempt.status,
                            actual_result=attempt.actual_result,
                        ))
                        continue
                    terminal = {"passed", "failed", "blocked", "skipped"}
                    if persisted.status in terminal and (
                        persisted.status != attempt.status
                        or persisted.actual_result != attempt.actual_result
                    ):
                        raise DomainError(
                            "ATTEMPT_TERMINAL_IMMUTABLE",
                            "Terminal case-run attempts cannot be overwritten",
                        )
                    allowed = {
                        ("not_run", "not_run"),
                        ("not_run", "running"),
                        ("running", "running"),
                        ("running", "passed"),
                        ("running", "failed"),
                        ("running", "blocked"),
                        ("running", "skipped"),
                    }
                    if persisted.status not in terminal and (
                        persisted.status,
                        attempt.status,
                    ) not in allowed:
                        raise DomainError(
                            "INVALID_CASE_RUN_TRANSITION",
                            "Persisted case-run transition is invalid",
                        )
                    persisted.status = attempt.status
                    persisted.actual_result = attempt.actual_result
        for revisions in self.reports.values():
            for value in revisions:
                report = value.report
                if self.session.get(TestReportRow, report.id) is None:
                    self.session.add(TestReportRow(
                        id=report.id, project_id=value.project_id, execution_id=report.execution_id,
                        revision=value.revision, published_by=report.published_by,
                        summary=report.summary, content_hash=report.content_hash,
                    ))

    def _save_automation(self) -> None:
        for value in self.automation_assets.values():
            self._put(self.session, AutomationAssetRow, value.id, {
                "id": value.id, "project_id": value.project_id,
                "normalized_name": " ".join(value.name.split()),
                "repository_ref": value.repository_ref, "case_version_ref": value.case_version_ref,
            })
        for value in self.automation_suites.values():
            self._put(self.session, AutomationSuiteRow, value.id, {
                "id": value.id, "project_id": value.project_id,
                "normalized_name": " ".join(value.name.split()),
                "asset_ids": [str(item) for item in value.asset_ids],
            })
        for value in self.automation_tasks.values():
            self._put(self.session, AutomationTaskRow, value.id, {
                "id": value.id, "project_id": value.project_id, "suite_id": value.suite_id,
                "environment_id": value.environment_id, "status": value.status,
                "external_run_ref": value.external_run_ref, "version": value.version,
            })
        for value in self.ingestions.values():
            if self.session.get(ResultIngestionRow, value.id) is not None:
                continue
            self.session.add(ResultIngestionRow(
                id=value.id, project_id=value.project_id, source=value.source,
                external_run_ref=value.external_run_ref, payload_hash=value.payload_hash,
            ))
            self.session.add_all([
                AutomationResultItemRow(
                    ingestion_id=value.id, sequence=index,
                    external_case_ref=item.external_case_ref, status=item.status,
                    case_version_ref=item.case_version_ref, duration_ms=item.duration_ms,
                    message=item.message,
                )
                for index, item in enumerate(value.items, start=1)
            ])

    def _save_traceability(self) -> None:
        for link in self.traceability_links.values():
            if self.session.get(TraceabilityLinkRow, link.id) is not None:
                continue
            self.session.add(TraceabilityLinkRow(
                id=link.id, project_id=link.source.project_id,
                source_id=link.source.resource_id, target_id=link.target.resource_id,
                source_domain=link.source.domain, source_type=link.source.resource_type,
                source_revision=link.source.revision, target_domain=link.target.domain,
                target_type=link.target.resource_type, target_revision=link.target.revision,
                link_type=link.link_type, status=link.status,
                source_event_id=link.source_event_id, occurred_at=link.occurred_at,
            ))

    def commit(self) -> None:
        """Persist domain rows, idempotency and Outbox events atomically."""
        try:
            self._save_library()
            self._save_sessions()
            self._save_execution_domain()
            self._save_automation()
            self._save_traceability()
            for (project_id, actor_id, key), value in self.idempotency.items():
                self._put(self.session, IdempotencyRecordRow, (project_id, actor_id, key), {
                    "project_id": project_id, "actor_id": actor_id, "idempotency_key": key,
                    "request_hash": value[0], "response_payload": value[1],
                    "response_status": value[2],
                })
            for event in self.outbox:
                self.session.add(OutboxEventRow(
                    id=uuid4(), event_type=str(event["event_type"]), payload=dict(event),
                    status="pending",
                ))
            self.outbox.clear()
            self.session.commit()
            self.commits += 1
        except Exception:
            self.session.rollback()
            raise

    def rollback(self) -> None:
        """Rollback the current SQLAlchemy transaction."""
        self.session.rollback()


class SqlAlchemyRuntime:
    """Engine and request-scoped TP sessions."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.sessions = scoped_session(sessionmaker(engine, expire_on_commit=False))

    def unit_of_work(self) -> SqlAlchemyUnitOfWork:
        """Create a UoW bound to the current request-scoped Session."""
        return SqlAlchemyUnitOfWork(self.sessions)

    def portal_repository(self) -> SqlAlchemyPortalRepository:
        """Create a read-only portal projection bound to the current Session.

        The portal never loads the full aggregate graph, so it deliberately
        bypasses :class:`SqlAlchemyUnitOfWork` and its eager ``_load`` pass.
        """
        return SqlAlchemyPortalRepository(self.sessions)

    def ready(self) -> None:
        """Raise when the private TP database is unavailable."""
        with self.engine.connect() as connection:
            connection.execute(text("SELECT 1"))

    def remove(self) -> None:
        """Remove the current scoped Session."""
        self.sessions.remove()


class AllowAllAuthorizer:
    """Explicit local authorizer; production IAM integration remains external."""

    def check(self, actor_id: UUID, project_id: UUID, action: str) -> bool:
        """Allow a well-formed scoped action."""
        return bool(actor_id and project_id and action)
