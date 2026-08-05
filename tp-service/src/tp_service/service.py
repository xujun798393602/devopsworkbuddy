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
    TestExecution,
    TestFolder,
    TestReport,
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


class Authorizer(Protocol):
    def check(self, actor_id: UUID, project_id: UUID, action: str) -> bool: ...


class UnitOfWork(Protocol):
    folders: dict[tuple[UUID, UUID], TestFolder]
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
