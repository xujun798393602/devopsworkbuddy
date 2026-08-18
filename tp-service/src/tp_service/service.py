"""TP application service for library, design gates and safe imports."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID, uuid4

from tp_service.design.safe_xmind import validate_xmind
from tp_service.domain import (
    DesignSession,
    DomainError,
    TestCase,
    TestCaseVersion,
    TestExecution,
    TestFolder,
    TestReport,
    TestStep,
    deterministic_mock,
)
from tp_service.execution import (
    AutomationIngestion,
    ManagedEnvironment,
    ManagedExecution,
    ManagedPlan,
    PlanScopeSnapshot,
    PublishedReport,
    ingest_automation_json,
    ingest_junit_xml,
)
from tp_service.repository import PortalExecutionSnapshot


class Authorizer(Protocol):
    def check(self, actor_id: UUID, project_id: UUID, action: str) -> bool: ...


class UnitOfWork(Protocol):
    folders: dict[tuple[UUID, UUID], TestFolder]
    cases: dict[tuple[UUID, UUID], TestCase]
    case_versions: dict[UUID, list[TestCaseVersion]]
    sessions: dict[tuple[UUID, UUID], DesignSession]
    import_batches: list[dict[str, Any]]
    outbox: list[dict[str, Any]]
    environments: dict[tuple[UUID, UUID], ManagedEnvironment]
    plans: dict[tuple[UUID, UUID], ManagedPlan]
    executions: dict[tuple[UUID, UUID], ManagedExecution]
    reports: dict[tuple[UUID, UUID], list[PublishedReport]]
    ingestions: dict[tuple[UUID, str, str], AutomationIngestion]

    def commit(self) -> None: ...

    def folder_descendants(self, project_id: UUID, folder_id: UUID) -> set[UUID]: ...

    def normalized_folder_name_exists(
        self,
        project_id: UUID,
        parent_id: UUID | None,
        name: str,
        excluding: UUID | None = None,
    ) -> bool: ...


@dataclass(slots=True)
class TpService:
    """Coordinate project-scoped TP commands with one local transaction each."""

    uow: UnitOfWork
    authorizer: Authorizer

    def _authorize(self, actor_id: UUID, project_id: UUID, action: str) -> None:
        if not self.authorizer.check(actor_id, project_id, action):
            raise DomainError("FORBIDDEN", "Permission denied", 403)

    def create_folder(
        self,
        actor_id: UUID,
        project_id: UUID,
        name: str,
        parent_id: UUID | None = None,
    ) -> TestFolder:
        """Create a sibling-unique folder in the same project."""
        self._authorize(actor_id, project_id, "test-folder:create")
        normalized_name = " ".join(name.split())
        if not normalized_name or len(normalized_name) > 200:
            raise DomainError("INVALID_FOLDER_NAME", "Folder name must contain 1 to 200 characters", 422)
        if parent_id is not None and (project_id, parent_id) not in self.uow.folders:
            raise DomainError("RESOURCE_NOT_FOUND", "Parent folder is not visible", 404)
        if self.uow.normalized_folder_name_exists(project_id, parent_id, normalized_name):
            raise DomainError("FOLDER_NAME_CONFLICT", "A sibling folder already uses this name")
        folder = TestFolder(uuid4(), project_id, normalized_name, parent_id)
        self.uow.folders[(project_id, folder.id)] = folder
        self.uow.outbox.append({"event_type": "TestFolder.Created", "project_id": str(project_id), "folder_id": str(folder.id)})
        return folder

    def move_folder(
        self,
        actor_id: UUID,
        project_id: UUID,
        folder_id: UUID,
        target_parent_id: UUID | None,
    ) -> TestFolder:
        """Move a folder with project, uniqueness, cycle and depth guards."""
        self._authorize(actor_id, project_id, "test-folder:move")
        folder = self.uow.folders.get((project_id, folder_id))
        if folder is None:
            raise DomainError("RESOURCE_NOT_FOUND", "Folder is not visible", 404)
        target = self.uow.folders.get((project_id, target_parent_id)) if target_parent_id else None
        if target_parent_id is not None and target is None:
            raise DomainError("RESOURCE_NOT_FOUND", "Target folder is not visible", 404)
        if self.uow.normalized_folder_name_exists(project_id, target_parent_id, folder.name, folder.id):
            raise DomainError("FOLDER_NAME_CONFLICT", "A sibling folder already uses this name")
        folder.move(target, self.uow.folder_descendants(project_id, folder.id))
        self.uow.outbox.append({"event_type": "TestFolder.Moved", "project_id": str(project_id), "folder_id": str(folder.id)})
        return folder

    def create_design_session(
        self,
        actor_id: UUID,
        project_id: UUID,
        requirement_snapshot_refs: tuple[str, ...],
        target_folder_id: UUID,
    ) -> DesignSession:
        """Create a draft design session with frozen requirement references."""
        self._authorize(actor_id, project_id, "test-design:create")
        if not requirement_snapshot_refs or (project_id, target_folder_id) not in self.uow.folders:
            raise DomainError("INVALID_DESIGN_SESSION", "Requirement snapshots and a visible folder are required", 422)
        session = DesignSession(uuid4(), project_id, actor_id, requirement_snapshot_refs, target_folder_id)
        self.uow.sessions[(project_id, session.id)] = session
        self.uow.outbox.append({"event_type": "DesignSession.Created", "project_id": str(project_id), "session_id": str(session.id)})
        return session

    def run_stage(self, actor_id: UUID, project_id: UUID, session_id: UUID, stage: str) -> DesignSession:
        """Run the explicit deterministic P0 mock and persist only metadata hashes."""
        self._authorize(actor_id, project_id, "test-design:run")
        session = self._session(project_id, session_id)
        input_payload = {"requirements": sorted(session.requirement_snapshot_refs), "stage": stage}
        canonical = json.dumps(input_payload, sort_keys=True, separators=(",", ":")).encode()
        run = session.start_stage(stage, hashlib.sha256(canonical).hexdigest())
        output = deterministic_mock(stage, input_payload)
        session.complete_stage(run, output)
        self.uow.outbox.append({"event_type": "DesignStage.Completed", "project_id": str(project_id), "session_id": str(session.id), "run_id": str(run.id), "provider": run.provider})
        return session

    def review_gate(
        self,
        actor_id: UUID,
        project_id: UUID,
        session_id: UUID,
        run_id: UUID,
        decision: str,
        privileged: bool = False,
        comments: str = "",
    ) -> DesignSession:
        """Apply an append-only human gate to the latest successful run."""
        self._authorize(actor_id, project_id, "test-design:review")
        session = self._session(project_id, session_id)
        run = next((item for item in session.runs if item.id == run_id), None)
        if run is None or run.status != "completed" or session.runs[-1].id != run_id:
            raise DomainError("STAGE_RUN_NOT_REVIEWABLE", "Latest successful run is required", 409)
        gate = session.apply_gate(
            run.stage,
            actor_id,
            decision,
            privileged,
            comments,
        )
        self.uow.outbox.append({"event_type": "DesignGate.Approved", "project_id": str(project_id), "session_id": str(session.id), "run_id": str(run.id), "reviewer_id": str(actor_id), "privileged": privileged, "review_gate_id": str(gate.id)})
        return session

    def import_xmind(
        self,
        actor_id: UUID,
        project_id: UUID,
        session_id: UUID,
        data: bytes,
        conflict_strategy: str,
    ) -> dict[str, Any]:
        """Validate a bounded XMind and atomically append an import batch."""
        self._authorize(actor_id, project_id, "test-design:import")
        session = self._session(project_id, session_id)
        if session.status.value != "ready_to_import" or session.approved_stages != {"analysis", "design", "cases"}:
            raise DomainError("GATE_REQUIRED", "Every stage requires a human approval")
        if conflict_strategy not in {"create_new", "update_if_same_source", "skip"}:
            raise DomainError("INVALID_CONFLICT_STRATEGY", "Unsupported import conflict strategy", 422)
        ir = validate_xmind(data)
        batch = {
            "id": str(uuid4()),
            "session_id": str(session.id),
            "source_hash": ir["content_hash"],
            "target_folder_id": str(session.target_folder_id),
            "conflict_strategy": conflict_strategy,
            "validation_summary": {"node_count": ir["node_count"], "case_count": ir["case_count"]},
            "status": "imported",
        }
        self.uow.import_batches.append(batch)
        session.mark_imported()
        self.uow.outbox.append({"event_type": "DesignSession.Imported", "project_id": str(project_id), "session_id": str(session.id), "batch_id": batch["id"]})
        return batch

    def create_plan(
        self,
        actor_id: UUID,
        project_id: UUID,
        owner_id: UUID,
        business_no: str,
    ) -> ManagedPlan:
        """Create a draft plan whose scope may be edited until frozen."""
        self._authorize(actor_id, project_id, "test-plan:create")
        normalized_no = business_no.strip()
        if not normalized_no or len(normalized_no) > 64:
            raise DomainError(
                "INVALID_PLAN_BUSINESS_NO",
                "Plan business number must contain 1 to 64 characters",
                422,
            )
        plan = ManagedPlan(uuid4(), project_id, normalized_no, owner_id)
        self.uow.plans[(project_id, plan.id)] = plan
        self._emit("TestPlan.Created", project_id, plan_id=plan.id)
        return plan

    def create_environment(
        self, actor_id: UUID, project_id: UUID, environment: ManagedEnvironment
    ) -> ManagedEnvironment:
        """Persist non-secret environment metadata in its owning project."""
        self._authorize(actor_id, project_id, "test-environment:create")
        if environment.project_id != project_id:
            raise DomainError("RESOURCE_NOT_FOUND", "Environment is not visible", 404)
        self.uow.environments[(project_id, environment.id)] = environment
        self._emit("TestEnvironment.Created", project_id, environment_id=environment.id)
        return environment

    def freeze_plan(
        self,
        actor_id: UUID,
        project_id: UUID,
        plan_id: UUID,
        scope: tuple[PlanScopeSnapshot, ...],
        valid_case_versions: set[UUID],
    ) -> ManagedPlan:
        """Freeze a plan using immutable requirement and case-version snapshots."""
        self._authorize(actor_id, project_id, "test-plan:freeze")
        plan = self._project_resource(self.uow.plans, project_id, plan_id, "Test plan")
        if any((project_id, item.environment_id) not in self.uow.environments for item in scope):
            raise DomainError("RESOURCE_NOT_FOUND", "A scope environment is not visible", 404)
        plan.freeze(scope, valid_case_versions)
        self._emit("TestPlan.ScopeFrozen", project_id, plan_id=plan.id, scope_hash=plan.scope_hash)
        return plan

    def create_case(
        self,
        actor_id: UUID,
        project_id: UUID,
        business_no: str,
        folder_id: UUID,
        title: str,
        owner_id: UUID,
        case_type: str,
        priority: str,
        automation_mode: str,
        requirement_refs: tuple[UUID, ...],
    ) -> TestCase:
        """Create a draft test case whose immutable content lives in versions."""
        self._authorize(actor_id, project_id, "test-case:create")
        if (project_id, folder_id) not in self.uow.folders:
            raise DomainError("RESOURCE_NOT_FOUND", "Folder is not visible", 404)
        normalized_no = business_no.strip()
        if not normalized_no:
            normalized_no = self._next_case_business_no(project_id)
        case = TestCase(
            uuid4(),
            project_id,
            normalized_no,
            folder_id,
            title,
            owner_id,
            case_type,
            priority,
            "draft",
            automation_mode,
            None,
            requirement_refs,
        )
        self.uow.cases[(project_id, case.id)] = case
        self._emit("TestCase.Created", project_id, case_id=str(case.id))
        return case

    def _next_case_business_no(self, project_id: UUID) -> str:
        """Generate a stable per-project business number for an empty input."""
        sequence = sum(1 for (scope, _), _ in self.uow.cases.items() if scope == project_id)
        return f"TC-{sequence + 1:04d}"

    def get_case(self, project_id: UUID, case_id: UUID) -> TestCase | None:
        """Return the case in the project scope or ``None`` when hidden."""
        return self.uow.cases.get((project_id, case_id))

    def list_cases(self, project_id: UUID) -> list[TestCase]:
        """Return all cases of a project in a stable, deterministic order."""
        cases = [case for (scope, _), case in self.uow.cases.items() if scope == project_id]
        cases.sort(key=lambda item: (str(item.business_no), str(item.id)))
        return cases

    def patch_case(
        self,
        actor_id: UUID,
        project_id: UUID,
        case_id: UUID,
        changes: dict[str, Any],
    ) -> TestCase:
        """Optimistic-concurrency head-metadata update (architecture §9.C.1).

        Only the mutable head fields are touched; the content snapshot is owned
        by :class:`TestCaseVersion`. The case is reconstructed so the domain
        ``__post_init__`` validation (title + enum checks) runs on the result.
        """
        self._authorize(actor_id, project_id, "test-case:patch")
        case = self._project_resource(self.uow.cases, project_id, case_id, "Test case")
        editable = {
            "folder_id",
            "title",
            "owner_id",
            "type",
            "priority",
            "status",
            "automation_mode",
            "requirement_refs",
        }
        updates = {key: changes[key] for key in editable if key in changes}
        if not updates:
            return case
        folder_id = case.folder_id
        if "folder_id" in updates:
            folder_id = UUID(str(updates["folder_id"]))
            if (project_id, folder_id) not in self.uow.folders:
                raise DomainError("RESOURCE_NOT_FOUND", "Folder is not visible", 404)
        owner_id = case.owner_id
        if "owner_id" in updates:
            owner_id = UUID(str(updates["owner_id"]))
        requirement_refs = case.requirement_refs
        if "requirement_refs" in updates:
            requirement_refs = tuple(UUID(str(item)) for item in updates["requirement_refs"])
        updated = TestCase(
            case.id,
            case.project_id,
            case.business_no,
            folder_id,
            str(updates.get("title", case.title)),
            owner_id,
            str(updates.get("type", case.type)),
            str(updates.get("priority", case.priority)),
            str(updates.get("status", case.status)),
            str(updates.get("automation_mode", case.automation_mode)),
            case.current_version_id,
            requirement_refs,
            version=case.version + 1,
        )
        self.uow.cases[(project_id, case.id)] = updated
        self._emit("TestCase.Patched", project_id, case_id=str(case.id))
        return updated

    def create_case_version(
        self,
        actor_id: UUID,
        project_id: UUID,
        case_id: UUID,
        steps: list[dict[str, Any]],
        source: str,
    ) -> TestCaseVersion:
        """Create an immutable version and publish it (§9.C.2)."""
        self._authorize(actor_id, project_id, "test-case:version:create")
        case = self._project_resource(self.uow.cases, project_id, case_id, "Test case")
        existing = self.uow.case_versions.get(case_id, [])
        version_no = len(existing) + 1
        test_steps = tuple(
            TestStep(
                int(step["sequence"]),
                str(step["action"]),
                str(step["expected"]),
                str(step.get("test_data", "")),
            )
            for step in steps
        )
        version = TestCaseVersion.create(case.id, version_no, test_steps, source)
        self.uow.case_versions.setdefault(case_id, []).append(version)
        case.publish(version)
        self._emit(
            "TestCase.VersionPublished",
            project_id,
            case_id=str(case.id),
            version_id=str(version.id),
        )
        return version

    def publish_case_version(
        self,
        actor_id: UUID,
        project_id: UUID,
        case_id: UUID,
        version_id: UUID,
    ) -> TestCaseVersion:
        """Publish an existing immutable version (§9.C.2 explicit mechanism)."""
        self._authorize(actor_id, project_id, "test-case:version:publish")
        case = self._project_resource(self.uow.cases, project_id, case_id, "Test case")
        version = next(
            (item for item in self.uow.case_versions.get(case_id, []) if item.id == version_id),
            None,
        )
        if version is None:
            raise DomainError("RESOURCE_NOT_FOUND", "Test case version is not visible", 404)
        case.publish(version)
        self._emit(
            "TestCase.VersionPublished",
            project_id,
            case_id=str(case.id),
            version_id=str(version.id),
        )
        return version

    def list_case_versions(self, case_id: UUID) -> list[TestCaseVersion]:
        """Return every version of a case in creation order."""
        return list(self.uow.case_versions.get(case_id, []))

    def get_case_version(self, version_id: UUID) -> TestCaseVersion | None:
        """Find a version across every case by id (§9.C.2)."""
        for versions in self.uow.case_versions.values():
            match = next((item for item in versions if item.id == version_id), None)
            if match is not None:
                return match
        return None

    def get_plan(self, project_id: UUID, plan_id: UUID) -> ManagedPlan | None:
        """Return the plan in the project scope or ``None`` when hidden."""
        return self.uow.plans.get((project_id, plan_id))

    def list_plans(self, project_id: UUID) -> list[ManagedPlan]:
        """Return all plans of a project in a stable, deterministic order."""
        plans = [plan for (scope, _), plan in self.uow.plans.items() if scope == project_id]
        plans.sort(key=lambda item: (str(item.business_no), str(item.id)))
        return plans

    def transition_plan(
        self,
        actor_id: UUID,
        project_id: UUID,
        plan_id: UUID,
        action: str,
        scope: tuple[PlanScopeSnapshot, ...],
        valid_case_versions: set[UUID],
        reason: str,
    ) -> ManagedPlan:
        """Apply one explicit lifecycle action to a plan (architecture §9.C.3).

        ``freeze`` routes to :meth:`freeze_plan`; the remaining actions map to the
        real transitions implemented by :class:`ManagedPlan`. Actions without a
        real target state (e.g. ``submit``/``approve``/``reject``/``activate`` of
        the aspirational doc vocabulary) are rejected because ``ManagedPlan`` has
        no such intermediate states, so we never invent phantom status values.
        """
        self._authorize(actor_id, project_id, "test-plan:transition")
        plan = self._project_resource(self.uow.plans, project_id, plan_id, "Test plan")
        if action == "freeze":
            plan.freeze(scope, valid_case_versions)
            self._emit("TestPlan.ScopeFrozen", project_id, plan_id=plan.id, scope_hash=plan.scope_hash)
            return plan
        target = PLAN_TRANSITION_TARGETS.get(action)
        if target is None:
            raise DomainError(
                "INVALID_PLAN_TRANSITION",
                f"Cannot apply action {action!r} to plan in status {plan.status}",
                422,
            )
        plan.transition(target)
        self._emit("TestPlan.Transitioned", project_id, plan_id=plan.id, action=action)
        return plan

    def create_execution(
        self,
        actor_id: UUID,
        project_id: UUID,
        plan_id: UUID,
        environment_id: UUID,
        assignee_id: UUID,
        round_no: int = 1,
    ) -> ManagedExecution:
        """Create an execution linked only to a visible frozen plan/environment."""
        self._authorize(actor_id, project_id, "test-execution:create")
        plan = self._project_resource(self.uow.plans, project_id, plan_id, "Test plan")
        self._project_resource(
            self.uow.environments,
            project_id,
            environment_id,
            "Test environment",
        )
        if plan.status != "ready" or round_no < 1:
            raise DomainError(
                "EXECUTION_NOT_CREATABLE",
                "A frozen plan and positive round number are required",
                422,
            )
        execution_id = uuid4()
        aggregate = TestExecution(
            execution_id,
            project_id,
            plan_id,
            environment_id,
            assignee_id,
        )
        execution = ManagedExecution(aggregate, round_no)
        self.uow.executions[(project_id, execution_id)] = execution
        self._emit("TestExecution.Created", project_id, execution_id=execution_id)
        return execution

    def start_execution(
        self, actor_id: UUID, project_id: UUID, execution_id: UUID
    ) -> ManagedExecution:
        """Start an execution strictly from its frozen plan snapshot."""
        self._authorize(actor_id, project_id, "test-execution:start")
        execution = self._project_resource(self.uow.executions, project_id, execution_id, "Execution")
        plan = self._project_resource(self.uow.plans, project_id, execution.aggregate.plan_id, "Test plan")
        if plan.status != "ready" or not plan.scope_hash:
            raise DomainError("PLAN_SCOPE_NOT_FROZEN", "Execution requires a ready frozen plan")
        execution.aggregate.start(tuple(item.case_version_ref for item in plan.scope))
        self._emit("TestExecution.Started", project_id, execution_id=execution_id)
        return execution

    def publish_report(
        self, actor_id: UUID, project_id: UUID, execution_id: UUID
    ) -> PublishedReport:
        """Append an immutable report revision without changing prior reports."""
        self._authorize(actor_id, project_id, "test-report:publish")
        execution = self._project_resource(self.uow.executions, project_id, execution_id, "Execution")
        report = TestReport.publish(execution.aggregate, actor_id)
        revisions = self.uow.reports.setdefault((project_id, execution_id), [])
        published = PublishedReport(report, project_id, len(revisions) + 1)
        revisions.append(published)
        self._emit("TestReport.Published", project_id, report_id=report.id, execution_id=execution_id)
        return published

    def ingest_results(
        self,
        actor_id: UUID,
        project_id: UUID,
        payload: bytes,
        mappings: dict[str, UUID],
        content_type: str = "application/json",
        source: str = "junit",
        external_run_ref: str = "",
    ) -> AutomationIngestion:
        """Persistently deduplicate bounded JSON or safe JUnit result ingestion."""
        self._authorize(actor_id, project_id, "automation-result:ingest")
        prior = self.uow.ingestions.get((project_id, source, external_run_ref))
        if content_type in {"application/xml", "text/xml"}:
            ingestion = ingest_junit_xml(project_id, payload, source, external_run_ref, mappings, prior)
        else:
            try:
                decoded = json.loads(payload)
                source = str(decoded.get("source", ""))
                external_run_ref = str(decoded.get("external_run_ref", ""))
            except (json.JSONDecodeError, AttributeError):
                pass
            prior = self.uow.ingestions.get((project_id, source, external_run_ref))
            ingestion = ingest_automation_json(project_id, payload, mappings, prior)
        key = (project_id, ingestion.source, ingestion.external_run_ref)
        existing = self.uow.ingestions.get(key)
        if existing is not None:
            if existing.payload_hash != ingestion.payload_hash:
                raise DomainError("INGESTION_PAYLOAD_CONFLICT", "Run reference already has another payload")
            return existing
        self.uow.ingestions[key] = ingestion
        self._emit("AutomationResult.Ingested", project_id, ingestion_id=ingestion.id)
        return ingestion

    def _emit(self, event_type: str, project_id: UUID, **values: object) -> None:
        event = {"event_type": event_type, "project_id": str(project_id)}
        event.update({key: str(value) for key, value in values.items()})
        self.uow.outbox.append(event)

    @staticmethod
    def _project_resource(store: dict[tuple[UUID, UUID], Any], project_id: UUID, resource_id: UUID, label: str) -> Any:
        resource = store.get((project_id, resource_id))
        if resource is None:
            raise DomainError("RESOURCE_NOT_FOUND", f"{label} is not visible", 404)
        return resource

    def _session(self, project_id: UUID, session_id: UUID) -> DesignSession:
        session = self.uow.sessions.get((project_id, session_id))
        if session is None:
            raise DomainError("RESOURCE_NOT_FOUND", "Design session is not visible", 404)
        return session


PORTAL_EXECUTION_LIMIT_DEFAULT = 5
PORTAL_EXECUTION_LIMIT_MAX = 50
PORTAL_EXECUTION_STATUS_KEYS: tuple[str, ...] = ("pending", "running", "passed", "failed")
PORTAL_TERMINAL_CASE_RUN_STATUSES = frozenset({"passed", "failed", "blocked", "skipped"})
PORTAL_FAILED_CASE_RUN_STATUSES = frozenset({"failed", "blocked"})
PORTAL_PENDING_EXECUTION_STATUS = "pending"

# Generic test-plan lifecycle actions exposed through the transitions endpoint
# (architecture §9.C.3). ``freeze`` is the documented alias for the frozen
# single-shot scope-freeze; the rest map onto ``ManagedPlan.transition``.
PLAN_TRANSITION_ACTIONS: tuple[str, ...] = (
    "freeze",
    "start_execution",
    "complete",
    "cancel",
    "close",
)
PLAN_TRANSITION_TARGETS: dict[str, str] = {
    "start_execution": "in_progress",
    "complete": "completed",
    "cancel": "canceled",
    "close": "closed",
}


class PortalRepository(Protocol):
    """Read-only port supplying batched portal projections."""

    def case_total(
        self,
        project_ids: tuple[UUID, ...] | list[UUID],
        cross_project: bool = False,
    ) -> int: ...

    def plan_total(
        self,
        project_ids: tuple[UUID, ...] | list[UUID],
        cross_project: bool = False,
    ) -> int: ...

    def executions(
        self,
        project_ids: tuple[UUID, ...] | list[UUID],
        cross_project: bool = False,
    ) -> list[PortalExecutionSnapshot]: ...


def derive_execution_status(snapshot: PortalExecutionSnapshot) -> str:
    """Derive the portal execution bucket from the TP execution and case runs.

    The four portal buckets partition every execution exactly once so that
    ``sum(execution_by_status.values()) == execution_total`` always holds:

    * ``pending``  - the execution has not been started yet (``draft``).
    * ``running``  - started but at least one latest case-run is not terminal.
    * ``failed``   - every latest case-run is terminal and at least one failed
      or was blocked.
    * ``passed``   - every latest case-run is terminal and none failed.
    """
    if snapshot.status == "draft":
        return PORTAL_PENDING_EXECUTION_STATUS
    counts = snapshot.latest_attempt_counts
    total = sum(counts.values())
    if total == 0:
        return "running"
    terminal = sum(
        value for status, value in counts.items() if status in PORTAL_TERMINAL_CASE_RUN_STATUSES
    )
    if terminal < total:
        return "running"
    failed = sum(
        value for status, value in counts.items() if status in PORTAL_FAILED_CASE_RUN_STATUSES
    )
    return "failed" if failed else "passed"


def portal_execution_name(snapshot: PortalExecutionSnapshot) -> str:
    """Compose a stable display name; TP executions carry no name column."""
    if snapshot.plan_business_no:
        return f"{snapshot.plan_business_no} R{snapshot.round_no}"
    return f"R{snapshot.round_no}"


def _portal_execution_item(snapshot: PortalExecutionSnapshot) -> dict[str, Any]:
    """Shape one pending execution item against the frozen portal contract.

    ``planned_at`` is always ``None``: ``test_executions`` has no scheduling
    timestamp column and the portal work explicitly excludes schema migrations.
    """
    return {
        "id": str(snapshot.id),
        "project_id": str(snapshot.project_id),
        "plan_id": str(snapshot.plan_id),
        "name": portal_execution_name(snapshot),
        "status": PORTAL_PENDING_EXECUTION_STATUS,
        "planned_at": None,
    }


@dataclass(slots=True)
class TpPortalService:
    """Aggregate read-only TP statistics for the platform dashboard."""

    repository: PortalRepository

    def summary(
        self,
        project_ids: tuple[UUID, ...] | list[UUID],
        actor_id: UUID | None = None,
        *,
        cross_project: bool = False,
        execution_limit: int = PORTAL_EXECUTION_LIMIT_DEFAULT,
    ) -> dict[str, Any]:
        """Return the frozen ``tp_stats`` payload for the requested scope."""
        scope = tuple(dict.fromkeys(project_ids))
        executions = self.repository.executions(scope, cross_project)
        by_status = dict.fromkeys(PORTAL_EXECUTION_STATUS_KEYS, 0)
        pending: list[PortalExecutionSnapshot] = []
        for snapshot in executions:
            derived = derive_execution_status(snapshot)
            by_status[derived] += 1
            if derived == PORTAL_PENDING_EXECUTION_STATUS:
                pending.append(snapshot)
        # The item list belongs to the "my work" card, so executions assigned to
        # the caller surface first while `count` still reports the whole scope.
        if actor_id is not None:
            pending.sort(key=lambda item: 0 if item.assignee_id == actor_id else 1)
        passed = by_status["passed"]
        failed = by_status["failed"]
        attempted = passed + failed
        return {
            "case_total": self.repository.case_total(scope, cross_project),
            "plan_total": self.repository.plan_total(scope, cross_project),
            "execution_total": len(executions),
            "execution_by_status": by_status,
            "pass_rate": round(passed / attempted, 2) if attempted else None,
            "pending_executions": {
                "count": len(pending),
                "items": [_portal_execution_item(item) for item in pending[:execution_limit]],
            },
        }
